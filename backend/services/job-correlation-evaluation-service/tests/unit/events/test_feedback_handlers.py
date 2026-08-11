"""Unit tests for events/feedback_handlers.py module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.job.correlation.v1 import FeedbackRecorded, FeedbackType
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _make_context(*, db_session: AsyncMock | None = None) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


class TestCreateMetadata:
    """Tests for create_event_metadata helper function from nohiki_db_utils."""

    def test_creates_metadata_with_correlation_id(self) -> None:
        """Test that metadata is created with correlation ID."""
        from nohiki_db_utils import create_event_metadata

        correlation_id = "test-correlation-id"
        metadata = create_event_metadata(
            source_service="job-correlation-evaluation-service",
            correlation_id=correlation_id,
        )

        assert metadata.correlation_id == correlation_id
        assert metadata.event_id is not None
        assert metadata.timestamp is not None


class TestHandleFeedbackRecorded:
    """Tests for handle_feedback_recorded handler."""

    @pytest.mark.asyncio
    async def test_records_feedback_successfully(self) -> None:
        """Test that feedback is recorded successfully."""
        mock_correlation = MagicMock()
        mock_correlation.id = uuid4()
        mock_correlation.user_id = uuid4()

        mock_service = MagicMock()
        mock_service.record_feedback = AsyncMock(return_value=mock_correlation)

        mock_message = MagicMock(spec=FeedbackRecorded)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.feedback_type = FeedbackType.LIKED

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"),
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationFeedbackService"
            ) as mock_service_class,
        ):
            mock_service_class.return_value = mock_service

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_feedback_recorded,
            )

            await handle_feedback_recorded(mock_message, context)

            mock_service.record_feedback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_correlation_not_found(self) -> None:
        """Test that CorrelationNotFoundError is handled gracefully."""
        from job_correlation_evaluation_service.repositories.correlation_repository import (
            CorrelationNotFoundError,
        )

        mock_service = MagicMock()
        mock_service.record_feedback = AsyncMock(side_effect=CorrelationNotFoundError(uuid4()))

        mock_message = MagicMock(spec=FeedbackRecorded)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.feedback_type = FeedbackType.DISLIKED

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"),
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationFeedbackService"
            ) as mock_service_class,
        ):
            mock_service_class.return_value = mock_service

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_feedback_recorded,
            )

            await handle_feedback_recorded(mock_message, context)


class TestHandleTrainingExportRequested:
    """Tests for handle_training_export_requested handler."""

    @pytest.mark.asyncio
    async def test_exports_training_data_successfully(self) -> None:
        """Test that training data is exported successfully."""
        mock_service = MagicMock()
        mock_service.export_training_data = AsyncMock(
            return_value=[
                {
                    "correlation_id": str(uuid4()),
                    "label": 1.0,
                    "features": [0.1, 0.2, 0.3],
                    "query_id": str(uuid4()),
                    "feature_schema_version": "test",
                },
            ]
        )

        mock_message = MagicMock()
        mock_message.command.operation_id = "test-request"
        mock_message.command.callback_topic = ""
        mock_message.command.caller_context = b""
        mock_message.command.attributes = {}
        mock_message.limit = 100
        mock_message.min_date = ""
        mock_message.max_date = ""

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"),
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationFeedbackService"
            ) as mock_service_class,
            patch("job_correlation_evaluation_service.events.feedback_handlers.kafka_client") as mock_kafka_client,
        ):
            mock_kafka_client.publish = AsyncMock()
            mock_service_class.return_value = mock_service

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_training_export_requested,
            )

            await handle_training_export_requested(mock_message, context)

            mock_service.export_training_data.assert_awaited_once()
            mock_kafka_client.publish.assert_awaited_once()
            event = mock_kafka_client.publish.call_args.args[1]
            assert event.success.samples[0].label == pytest.approx(1.0)
            assert event.success.samples[0].features == pytest.approx([0.1, 0.2, 0.3])

    @pytest.mark.asyncio
    async def test_uses_default_limit_when_zero(self) -> None:
        """Test that default limit is used when limit is zero."""
        mock_service = MagicMock()
        mock_service.export_training_data = AsyncMock(return_value=[])

        mock_message = MagicMock()
        mock_message.command.operation_id = "test-request"
        mock_message.command.callback_topic = ""
        mock_message.command.caller_context = b""
        mock_message.command.attributes = {}
        mock_message.limit = 0
        mock_message.min_date = ""
        mock_message.max_date = ""

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"),
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationFeedbackService"
            ) as mock_service_class,
            patch("job_correlation_evaluation_service.events.feedback_handlers.kafka_client") as mock_kafka_client,
        ):
            mock_kafka_client.publish = AsyncMock()
            mock_service_class.return_value = mock_service

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_training_export_requested,
            )

            await handle_training_export_requested(mock_message, context)

            call_kwargs = mock_service.export_training_data.call_args.kwargs
            assert call_kwargs["limit"] == 10000

    @pytest.mark.asyncio
    async def test_parses_date_filters(self) -> None:
        """Test that date filters are parsed correctly."""
        mock_service = MagicMock()
        mock_service.export_training_data = AsyncMock(return_value=[])

        mock_message = MagicMock()
        mock_message.command.operation_id = "test-request"
        mock_message.command.callback_topic = ""
        mock_message.command.caller_context = b""
        mock_message.command.attributes = {}
        mock_message.limit = 100
        mock_message.min_date = "2024-01-01T00:00:00"
        mock_message.max_date = "2024-12-31T23:59:59"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"),
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationFeedbackService"
            ) as mock_service_class,
            patch("job_correlation_evaluation_service.events.feedback_handlers.kafka_client") as mock_kafka_client,
        ):
            mock_kafka_client.publish = AsyncMock()
            mock_service_class.return_value = mock_service

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_training_export_requested,
            )

            await handle_training_export_requested(mock_message, context)

            call_kwargs = mock_service.export_training_data.call_args.kwargs
            assert call_kwargs["min_date"] is not None
            assert call_kwargs["max_date"] is not None

    @pytest.mark.asyncio
    async def test_handles_invalid_date_formats(self) -> None:
        """Test that invalid date formats are handled gracefully."""
        mock_service = MagicMock()
        mock_service.export_training_data = AsyncMock(return_value=[])

        mock_message = MagicMock()
        mock_message.command.operation_id = "test-request"
        mock_message.command.callback_topic = ""
        mock_message.command.caller_context = b""
        mock_message.command.attributes = {}
        mock_message.limit = 100
        mock_message.min_date = "invalid-date"
        mock_message.max_date = "also-invalid"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"),
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationFeedbackService"
            ) as mock_service_class,
            patch("job_correlation_evaluation_service.events.feedback_handlers.kafka_client") as mock_kafka_client,
        ):
            mock_kafka_client.publish = AsyncMock()
            mock_service_class.return_value = mock_service

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_training_export_requested,
            )

            await handle_training_export_requested(mock_message, context)

            call_kwargs = mock_service.export_training_data.call_args.kwargs
            assert call_kwargs["min_date"] is None
            assert call_kwargs["max_date"] is None


class TestHandleScoreFeedbackRequested:
    """Tests for handle_score_feedback_requested handler."""

    @pytest.mark.asyncio
    async def test_creates_asymmetric_feedback_successfully(self) -> None:
        """Test that asymmetric feedback is created successfully."""
        from nohiki.feedback.v1 import ScoreFeedbackRequested, ScoreFeedbackType

        mock_feedback = MagicMock()
        mock_feedback.id = uuid4()

        mock_repo = MagicMock()
        mock_repo.create_asymmetric_feedback = AsyncMock(return_value=mock_feedback)
        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=MagicMock())

        mock_message = MagicMock(spec=ScoreFeedbackRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.feedback_type = ScoreFeedbackType.GOOD

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository") as mock_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_correlation_repo_class,
        ):
            mock_repo_class.return_value = mock_repo
            mock_correlation_repo_class.return_value = mock_correlation_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_feedback_requested,
            )

            await handle_score_feedback_requested(mock_message, context)

            mock_repo.create_asymmetric_feedback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_too_high_feedback_type(self) -> None:
        """Test that TOO_HIGH feedback type is handled correctly."""
        from nohiki.feedback.v1 import ScoreFeedbackRequested, ScoreFeedbackType

        mock_feedback = MagicMock()
        mock_feedback.id = uuid4()

        mock_repo = MagicMock()
        mock_repo.create_asymmetric_feedback = AsyncMock(return_value=mock_feedback)
        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=MagicMock())

        mock_message = MagicMock(spec=ScoreFeedbackRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.feedback_type = ScoreFeedbackType.TOO_HIGH

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository") as mock_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_correlation_repo_class,
        ):
            mock_repo_class.return_value = mock_repo
            mock_correlation_repo_class.return_value = mock_correlation_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_feedback_requested,
            )

            await handle_score_feedback_requested(mock_message, context)

            call_kwargs = mock_repo.create_asymmetric_feedback.call_args.kwargs
            assert call_kwargs["feedback_type"] == ScoreFeedbackType.TOO_HIGH

    @pytest.mark.asyncio
    async def test_handles_too_low_feedback_type(self) -> None:
        """Test that TOO_LOW feedback type is handled correctly."""
        from nohiki.feedback.v1 import ScoreFeedbackRequested, ScoreFeedbackType

        mock_feedback = MagicMock()
        mock_feedback.id = uuid4()

        mock_repo = MagicMock()
        mock_repo.create_asymmetric_feedback = AsyncMock(return_value=mock_feedback)
        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=MagicMock())

        mock_message = MagicMock(spec=ScoreFeedbackRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.feedback_type = ScoreFeedbackType.TOO_LOW

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository") as mock_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_correlation_repo_class,
        ):
            mock_repo_class.return_value = mock_repo
            mock_correlation_repo_class.return_value = mock_correlation_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_feedback_requested,
            )

            await handle_score_feedback_requested(mock_message, context)

            call_kwargs = mock_repo.create_asymmetric_feedback.call_args.kwargs
            assert call_kwargs["feedback_type"] == ScoreFeedbackType.TOO_LOW


class TestHandleScoreAdjustmentRequested:
    """Tests for handle_score_adjustment_requested handler."""

    @pytest.mark.asyncio
    async def test_creates_manual_adjustment_successfully(self) -> None:
        """Test that manual adjustment is created successfully."""
        from nohiki.feedback.v1 import ScoreAdjustmentRequested

        mock_correlation = MagicMock()
        mock_correlation.correlation_score = 75

        mock_adjustment = MagicMock()
        mock_adjustment.id = uuid4()

        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=mock_correlation)

        mock_feedback_repo = MagicMock()
        mock_feedback_repo.create_manual_adjustment = AsyncMock(return_value=mock_adjustment)

        mock_message = MagicMock(spec=ScoreAdjustmentRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.adjusted_score = 0.45
        mock_message.reasoning = "Skills mismatch with requirements"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_corr_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository"
            ) as mock_fb_repo_class,
        ):
            mock_corr_repo_class.return_value = mock_correlation_repo
            mock_fb_repo_class.return_value = mock_feedback_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_adjustment_requested,
            )

            await handle_score_adjustment_requested(mock_message, context)

            mock_correlation_repo.get_by_id.assert_awaited_once()
            mock_feedback_repo.create_manual_adjustment.assert_awaited_once()

            adjustment = mock_feedback_repo.create_manual_adjustment.call_args.args[2]
            assert abs(adjustment.original_score - 0.75) < 1e-9
            assert abs(adjustment.adjusted_score - 0.45) < 1e-9
            assert adjustment.reasoning == "Skills mismatch with requirements"

    @pytest.mark.asyncio
    async def test_handles_correlation_not_found(self) -> None:
        """Test that missing correlation is handled gracefully."""
        from nohiki.feedback.v1 import ScoreAdjustmentRequested

        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=None)

        mock_feedback_repo = MagicMock()
        mock_feedback_repo.create_manual_adjustment = AsyncMock()

        mock_message = MagicMock(spec=ScoreAdjustmentRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.adjusted_score = 0.45
        mock_message.reasoning = "Skills mismatch"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_corr_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository"
            ) as mock_fb_repo_class,
        ):
            mock_corr_repo_class.return_value = mock_correlation_repo
            mock_fb_repo_class.return_value = mock_feedback_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_adjustment_requested,
            )

            await handle_score_adjustment_requested(mock_message, context)

            mock_correlation_repo.get_by_id.assert_awaited_once()
            mock_feedback_repo.create_manual_adjustment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_null_correlation_score(self) -> None:
        """Test that null correlation score defaults to 0.0."""
        from nohiki.feedback.v1 import ScoreAdjustmentRequested

        mock_correlation = MagicMock()
        mock_correlation.correlation_score = None

        mock_adjustment = MagicMock()
        mock_adjustment.id = uuid4()

        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=mock_correlation)

        mock_feedback_repo = MagicMock()
        mock_feedback_repo.create_manual_adjustment = AsyncMock(return_value=mock_adjustment)

        mock_message = MagicMock(spec=ScoreAdjustmentRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.adjusted_score = 0.65
        mock_message.reasoning = "Score needs adjustment"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_corr_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository"
            ) as mock_fb_repo_class,
        ):
            mock_corr_repo_class.return_value = mock_correlation_repo
            mock_fb_repo_class.return_value = mock_feedback_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_adjustment_requested,
            )

            await handle_score_adjustment_requested(mock_message, context)

            adjustment = mock_feedback_repo.create_manual_adjustment.call_args.args[2]
            assert abs(adjustment.original_score - 0.0) < 1e-9

    @pytest.mark.asyncio
    async def test_handles_edge_case_scores(self) -> None:
        """Test that edge case scores (0 and 100) are handled correctly."""
        from nohiki.feedback.v1 import ScoreAdjustmentRequested

        mock_correlation = MagicMock()
        mock_correlation.correlation_score = 100

        mock_adjustment = MagicMock()
        mock_adjustment.id = uuid4()

        mock_correlation_repo = MagicMock()
        mock_correlation_repo.get_by_id = AsyncMock(return_value=mock_correlation)

        mock_feedback_repo = MagicMock()
        mock_feedback_repo.create_manual_adjustment = AsyncMock(return_value=mock_adjustment)

        mock_message = MagicMock(spec=ScoreAdjustmentRequested)
        mock_message.request_id = "test-request"
        mock_message.correlation_id = str(uuid4())
        mock_message.user_id = str(uuid4())
        mock_message.adjusted_score = 0.0
        mock_message.reasoning = "Completely irrelevant match"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.CorrelationRepository"
            ) as mock_corr_repo_class,
            patch(
                "job_correlation_evaluation_service.events.feedback_handlers.FeedbackRepository"
            ) as mock_fb_repo_class,
        ):
            mock_corr_repo_class.return_value = mock_correlation_repo
            mock_fb_repo_class.return_value = mock_feedback_repo

            from job_correlation_evaluation_service.events.feedback_handlers import (
                handle_score_adjustment_requested,
            )

            await handle_score_adjustment_requested(mock_message, context)

            adjustment = mock_feedback_repo.create_manual_adjustment.call_args.args[2]
            assert abs(adjustment.original_score - 1.0) < 1e-9
            assert abs(adjustment.adjusted_score - 0.0) < 1e-9

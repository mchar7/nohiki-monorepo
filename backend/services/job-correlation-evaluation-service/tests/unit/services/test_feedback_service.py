"""Unit tests for CorrelationFeedbackService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from job_correlation_evaluation_service.services.feedback_service import (
    CorrelationFeedbackService,
)
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT
from nohiki.common.v1 import UserFeedback
from nohiki.job.correlation.v1 import FeedbackType


class TestCorrelationFeedbackServiceLabelMap:
    """Tests for LABEL_MAP class variable."""

    def test_label_map_keys(self) -> None:
        """Verify expected feedback types have labels."""
        expected_keys = {
            "applied",
            "liked",
            "saved",
            "viewed",
            "dismissed",
            "disliked",
            "not_interested",
        }
        assert set(CorrelationFeedbackService.LABEL_MAP.keys()) == expected_keys

    def test_label_map_applied_highest(self) -> None:
        """Verify applied has highest label."""
        assert CorrelationFeedbackService.LABEL_MAP["applied"] == pytest.approx(5.0)

    def test_label_map_disliked_lowest(self) -> None:
        """Verify disliked has lowest (zero) label."""
        assert CorrelationFeedbackService.LABEL_MAP["disliked"] == pytest.approx(0.0)

    def test_label_map_ordering(self) -> None:
        """Verify labels follow expected ordering."""
        lm = CorrelationFeedbackService.LABEL_MAP
        assert lm["applied"] > lm["liked"]
        assert lm["liked"] > lm["saved"]
        assert lm["saved"] > lm["viewed"]
        assert lm["viewed"] > lm["dismissed"]
        assert lm["dismissed"] > lm["disliked"]


class TestRecordFeedback:
    """Tests for record_feedback method."""

    @pytest.fixture
    def mock_repository(self) -> AsyncMock:
        """Create mock CorrelationRepository."""
        repo = AsyncMock()
        mock_correlation = MagicMock()
        mock_correlation.id = uuid4()
        repo.update.return_value = mock_correlation
        return repo

    @pytest.fixture
    def feedback_service(self, mock_repository: AsyncMock) -> CorrelationFeedbackService:
        """Create feedback service with mock repository."""
        return CorrelationFeedbackService(repository=mock_repository)

    @pytest.mark.asyncio
    async def test_record_viewed(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording VIEWED feedback."""
        correlation_id = uuid4()

        await feedback_service.record_feedback(
            correlation_id=correlation_id,
            feedback_type=FeedbackType.VIEWED,
        )

        mock_repository.update.assert_called_once_with(correlation_id, is_viewed=True)

    @pytest.mark.asyncio
    async def test_record_applied(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording APPLIED feedback sets both is_applied and is_viewed."""
        correlation_id = uuid4()

        await feedback_service.record_feedback(
            correlation_id=correlation_id,
            feedback_type=FeedbackType.APPLIED,
        )

        mock_repository.update.assert_called_once_with(
            correlation_id,
            is_applied=True,
            is_viewed=True,
        )

    @pytest.mark.asyncio
    async def test_record_dismissed(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording DISMISSED feedback."""
        correlation_id = uuid4()

        await feedback_service.record_feedback(
            correlation_id=correlation_id,
            feedback_type=FeedbackType.DISMISSED,
        )

        mock_repository.update.assert_called_once_with(correlation_id, is_dismissed=True)

    @pytest.mark.asyncio
    async def test_record_saved(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording SAVED feedback sets positive user_feedback."""
        correlation_id = uuid4()

        await feedback_service.record_feedback(
            correlation_id=correlation_id,
            feedback_type=FeedbackType.SAVED,
        )

        mock_repository.update.assert_called_once_with(
            correlation_id,
            user_feedback=UserFeedback.POSITIVE,
            is_viewed=True,
        )

    @pytest.mark.asyncio
    async def test_record_liked(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording LIKED feedback sets positive user_feedback."""
        correlation_id = uuid4()

        await feedback_service.record_feedback(
            correlation_id=correlation_id,
            feedback_type=FeedbackType.LIKED,
        )

        mock_repository.update.assert_called_once_with(
            correlation_id,
            user_feedback=UserFeedback.POSITIVE,
            is_viewed=True,
        )

    @pytest.mark.asyncio
    async def test_record_disliked(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test recording DISLIKED feedback sets negative user_feedback."""
        correlation_id = uuid4()

        await feedback_service.record_feedback(
            correlation_id=correlation_id,
            feedback_type=FeedbackType.DISLIKED,
        )

        mock_repository.update.assert_called_once_with(
            correlation_id,
            user_feedback=UserFeedback.NEGATIVE,
        )

    @pytest.mark.asyncio
    async def test_record_unknown_feedback_raises(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test recording unknown feedback type raises ValueError."""
        correlation_id = uuid4()

        with pytest.raises(ValueError, match="Unknown feedback type"):
            await feedback_service.record_feedback(
                correlation_id=correlation_id,
                feedback_type=FeedbackType.UNSPECIFIED,
            )

    @pytest.mark.asyncio
    async def test_cross_user_feedback_is_rejected(self) -> None:
        """A user cannot mutate a correlation owned by another user."""
        from typing import cast

        from job_correlation_evaluation_service.repositories.correlation_repository import (
            CorrelationNotFoundError,
            CorrelationRepository,
        )

        correlation_id = uuid4()
        owner_id = uuid4()

        class OwnershipAwareRepository:
            async def update(
                self,
                requested_id: object,
                *,
                user_id: object | None = None,
                **changes: object,
            ) -> MagicMock:
                del changes
                if requested_id != correlation_id or (user_id is not None and user_id != owner_id):
                    raise CorrelationNotFoundError(correlation_id)
                return MagicMock()

        service = CorrelationFeedbackService(cast(CorrelationRepository, OwnershipAwareRepository()))

        with pytest.raises(CorrelationNotFoundError):
            await service.record_feedback(
                correlation_id=correlation_id,
                feedback_type=FeedbackType.VIEWED,
                user_id=uuid4(),
            )


class TestGetStats:
    """Tests for get_stats method."""

    @pytest.mark.asyncio
    async def test_get_stats_delegates_to_repository(self) -> None:
        """Test get_stats delegates to repository."""
        mock_repo = AsyncMock()
        mock_repo.get_feedback_stats.return_value = {
            "total_feedback_count": 100,
            "feedback_by_type": {"viewed": 80, "applied": 20},
            "training_samples_available": 50,
        }

        service = CorrelationFeedbackService(repository=mock_repo)
        stats = await service.get_stats()

        mock_repo.get_feedback_stats.assert_called_once()
        assert stats["total_feedback_count"] == 100


class TestExportTrainingData:
    """Tests for export_training_data method."""

    @pytest.fixture
    def mock_repository(self) -> AsyncMock:
        """Create mock repository with training data."""
        return AsyncMock()

    @pytest.fixture
    def feedback_service(self, mock_repository: AsyncMock) -> CorrelationFeedbackService:
        """Create feedback service with mock repository."""
        return CorrelationFeedbackService(repository=mock_repository)

    def _make_correlation(
        self,
        *,
        is_applied: bool = False,
        is_viewed: bool = False,
        is_dismissed: bool = False,
        user_feedback: UserFeedback | None = None,
        feature_vector: list[float] | None = None,
    ) -> MagicMock:
        """Create mock correlation with specified attributes."""
        corr = MagicMock()
        corr.id = uuid4()
        corr.user_id = uuid4()
        corr.is_applied = is_applied
        corr.is_viewed = is_viewed
        corr.is_dismissed = is_dismissed
        corr.user_feedback = user_feedback
        corr.feature_vector = feature_vector
        return corr

    @pytest.mark.asyncio
    async def test_export_applied_label(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test applied correlation gets label 5.0."""
        corr = self._make_correlation(
            is_applied=True,
            feature_vector=[0.5] * FEATURE_COUNT,
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert len(samples) == 1
        assert samples[0]["label"] == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_export_positive_feedback_label(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test positive feedback correlation gets label 4.0."""
        corr = self._make_correlation(
            user_feedback=UserFeedback.POSITIVE,
            feature_vector=[0.5] * FEATURE_COUNT,
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert len(samples) == 1
        assert samples[0]["label"] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_export_viewed_label(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test viewed (not dismissed) correlation gets label 2.0."""
        corr = self._make_correlation(
            is_viewed=True,
            feature_vector=[0.5] * FEATURE_COUNT,
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert len(samples) == 1
        assert samples[0]["label"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_export_dismissed_label(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test dismissed correlation gets label 0.5."""
        corr = self._make_correlation(
            is_dismissed=True,
            feature_vector=[0.5] * FEATURE_COUNT,
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert len(samples) == 1
        assert samples[0]["label"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_export_negative_feedback_label(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test negative feedback correlation gets label 0.0."""
        corr = self._make_correlation(
            user_feedback=UserFeedback.NEGATIVE,
            feature_vector=[0.5] * FEATURE_COUNT,
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert len(samples) == 1
        assert samples[0]["label"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_export_skips_no_feedback(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test correlations without feedback signals are skipped."""
        corr = self._make_correlation(
            feature_vector=[0.5] * FEATURE_COUNT,
            # No feedback signals
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        # No label computable, so no samples
        assert len(samples) == 0

    @pytest.mark.asyncio
    async def test_export_skips_no_features(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test correlations without feature vectors are skipped."""
        corr = self._make_correlation(
            is_applied=True,
            feature_vector=None,  # No features
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert len(samples) == 0

    @pytest.mark.asyncio
    async def test_export_includes_query_id(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test export includes user_id as query_id for LambdaMART."""
        corr = self._make_correlation(
            is_applied=True,
            feature_vector=[0.5] * FEATURE_COUNT,
        )
        mock_repository.get_for_training.return_value = [corr]

        samples = await feedback_service.export_training_data()

        assert "query_id" in samples[0]
        assert samples[0]["query_id"] == str(corr.user_id)

    @pytest.mark.asyncio
    async def test_export_with_date_filters(
        self,
        feedback_service: CorrelationFeedbackService,
        mock_repository: AsyncMock,
    ) -> None:
        """Test export passes date filters to repository."""
        mock_repository.get_for_training.return_value = []
        min_date = datetime(2024, 1, 1, tzinfo=UTC)
        max_date = datetime(2024, 12, 31, tzinfo=UTC)

        await feedback_service.export_training_data(
            min_date=min_date,
            max_date=max_date,
            limit=5000,
        )

        mock_repository.get_for_training.assert_called_once_with(
            min_date=min_date,
            max_date=max_date,
            limit=5000,
        )


class TestComputeLabel:
    """Tests for _compute_label internal method."""

    @pytest.fixture
    def feedback_service(self) -> CorrelationFeedbackService:
        """Create feedback service with mock repository."""
        return CorrelationFeedbackService(repository=AsyncMock())

    def _make_correlation(
        self,
        *,
        is_applied: bool = False,
        is_viewed: bool = False,
        is_dismissed: bool = False,
        user_feedback: UserFeedback | None = None,
    ) -> MagicMock:
        """Create mock correlation."""
        corr = MagicMock()
        corr.is_applied = is_applied
        corr.is_viewed = is_viewed
        corr.is_dismissed = is_dismissed
        corr.user_feedback = user_feedback
        return corr

    def test_applied_takes_precedence(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test applied takes precedence over other signals."""
        corr = self._make_correlation(
            is_applied=True,
            is_viewed=True,
            user_feedback=UserFeedback.POSITIVE,
        )

        label = feedback_service._compute_label(corr)

        assert label == pytest.approx(5.0)

    def test_positive_feedback_over_viewed(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test positive feedback takes precedence over just viewed."""
        corr = self._make_correlation(
            is_viewed=True,
            user_feedback=UserFeedback.POSITIVE,
        )

        label = feedback_service._compute_label(corr)

        assert label == pytest.approx(4.0)

    def test_viewed_dismissed_returns_dismissed_label(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test viewed + dismissed returns dismissed label (0.5)."""
        corr = self._make_correlation(
            is_viewed=True,
            is_dismissed=True,
        )

        label = feedback_service._compute_label(corr)

        assert label == pytest.approx(0.5)

    def test_no_signals_returns_none(
        self,
        feedback_service: CorrelationFeedbackService,
    ) -> None:
        """Test no feedback signals returns None."""
        corr = self._make_correlation()

        label = feedback_service._compute_label(corr)

        assert label is None

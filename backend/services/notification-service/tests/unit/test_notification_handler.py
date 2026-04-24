"""Tests for notification_handler module.

Tests the generic notification event handler and its helper functions.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.common.v1 import (
    EmailDestination,
    ErrorInfo,
    NotificationChannel,
    NotificationMethod,
    OperationOutcome,
    ProcessingStatus,
    SearchPrefNotificationConfig,
)
from nohiki.doc.content.v1 import ContentGenerationCompleted
from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki.job.listing.v1 import ListingNotificationSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from notification_service.db.models import MessageStatus
from notification_service.services.notification_handler import (
    NotificationSendParams,
    _format_subject,
    _send_notification,
    handle_notification_event,
)
from notification_service.services.template_registry import (
    EVENT_TYPE_CONTENT_GENERATION_COMPLETED,
    EVENT_TYPE_CORRELATION_EVALUATED,
)


def _create_notification_config(
    *,
    threshold: int = 80,
    email: str = "test@example.com",
    enabled: bool = True,
) -> SearchPrefNotificationConfig:
    """Create a notification config with email method for testing."""
    methods: list[NotificationMethod] = []
    if email:
        methods.append(
            NotificationMethod(
                enabled=enabled,
                channel=NotificationChannel.EMAIL,
                email=EmailDestination(email_address=email),
            )
        )
    return SearchPrefNotificationConfig(threshold=threshold, methods=methods)


def _create_pref_snapshot(
    pref_id: str,
    user_id: str,
    *,
    threshold: int = 80,
    email: str = "test@example.com",
    email_enabled: bool = True,
) -> SearchPrefSnapshot:
    """Create a SearchPrefSnapshot with notification config."""
    return SearchPrefSnapshot(
        id=pref_id,
        user_id=user_id,
        pref_name="Test Pref",
        search_keywords=["test"],
        notification_config=_create_notification_config(threshold=threshold, email=email, enabled=email_enabled),
    )


def _create_listing_snapshot(listing_id: str) -> ListingNotificationSnapshot:
    """Create a ListingNotificationSnapshot for testing."""
    return ListingNotificationSnapshot(
        id=listing_id,
        title="Software Engineer",
        company_name="TechCorp",
        listing_url="https://example.com/job",
    )


def _create_context() -> MagicMock:
    """Create a mock MessageContext."""
    context = MagicMock(spec=MessageContext)
    context.correlation_id = str(uuid.uuid4())
    return context


class TestFormatSubject:
    """Tests for _format_subject function."""

    def test_formats_template_with_complete_context(self) -> None:
        """Should format template when all keys present in context."""
        template = "New Job: {title} at {company}"
        context: dict[str, str | int | None] = {
            "title": "Software Engineer",
            "company": "TechCorp",
        }

        result = _format_subject(template, context)

        assert result == "New Job: Software Engineer at TechCorp"

    def test_returns_template_when_context_missing_keys(self) -> None:
        """Should return original template when context is missing keys."""
        template = "New Job: {title} at {company}"
        context: dict[str, str | int | None] = {"title": "Software Engineer"}

        result = _format_subject(template, context)

        assert result == template

    def test_handles_empty_context(self) -> None:
        """Should return template unchanged with empty context."""
        template = "Job Alert: {title}"
        context: dict[str, str | int | None] = {}

        result = _format_subject(template, context)

        assert result == template

    def test_handles_template_without_placeholders(self) -> None:
        """Should return template as-is when no placeholders present."""
        template = "New job notification"
        context: dict[str, str | int | None] = {"title": "Software Engineer"}

        result = _format_subject(template, context)

        assert result == "New job notification"


class TestSendNotification:
    """Tests for _send_notification function."""

    @pytest.mark.asyncio
    async def test_creates_correct_params_and_sends(self) -> None:
        """Should create BatchJobNotificationParams and send via MessageService."""
        user_id = str(uuid.uuid4())
        listing_id = str(uuid.uuid4())
        template_context: dict[str, str | int | None] = {
            "listing_id": listing_id,
            "listing_title": "Software Engineer",
            "company_name": "TechCorp",
        }

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(return_value=[MagicMock()])
            mock_service_class.return_value = mock_service

            params = NotificationSendParams(
                template_name="job_match",
                subject="New Job Match",
                template_context=template_context,
                email_address="test@example.com",
                user_id=user_id,
                correlation_id="corr-123",
            )
            await _send_notification(params, db=create_mock_session())

            mock_service.send_job_notification_ecst.assert_called_once()
            call_kwargs = mock_service.send_job_notification_ecst.call_args.kwargs
            assert call_kwargs["recipient_email"] == "test@example.com"

            batch_params = call_kwargs["params"]
            assert str(batch_params.user_id) == user_id
            assert batch_params.subject == "New Job Match"
            assert batch_params.channels == ["email"]

    @pytest.mark.asyncio
    async def test_uses_user_id_as_fallback_for_listing_id(self) -> None:
        """Should use user_id when listing_id not in context."""
        user_id = str(uuid.uuid4())
        template_context: dict[str, str | int | None] = {"listing_title": "Software Engineer"}

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(return_value=[MagicMock()])
            mock_service_class.return_value = mock_service

            params = NotificationSendParams(
                template_name="job_match",
                subject="New Job Match",
                template_context=template_context,
                email_address="test@example.com",
                user_id=user_id,
                correlation_id="corr-123",
            )
            await _send_notification(params, db=create_mock_session())

            call_kwargs = mock_service.send_job_notification_ecst.call_args.kwargs
            batch_params = call_kwargs["params"]
            # listing_id should fallback to user_id
            assert str(batch_params.listing_id) == user_id

    @pytest.mark.asyncio
    async def test_reraises_exception_on_failure(self) -> None:
        """Should re-raise exception when MessageService fails."""
        user_id = str(uuid.uuid4())
        listing_id = str(uuid.uuid4())
        template_context: dict[str, str | int | None] = {"listing_id": listing_id}

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(side_effect=RuntimeError("Send failed"))
            mock_service_class.return_value = mock_service

            params = NotificationSendParams(
                template_name="job_match",
                subject="New Job Match",
                template_context=template_context,
                email_address="test@example.com",
                user_id=user_id,
                correlation_id="corr-123",
            )
            with pytest.raises(RuntimeError, match="Send failed"):
                await _send_notification(params, db=create_mock_session())


class TestHandleNotificationEvent:
    """Tests for handle_notification_event function."""

    @pytest.mark.asyncio
    async def test_skips_when_no_template_registered(self) -> None:
        """Should skip and log warning when event type not in registry."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()))
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            await handle_notification_event("unknown.event.type", event, context)

            mock_service.send_job_notification_ecst.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_error_when_pref_snapshot_is_none(self) -> None:
        """Should raise ValueError when pref_snapshot is None."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            listing_snapshot=listing_snapshot,
        )

        with pytest.raises(ValueError, match="pref_snapshot is required"):
            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

    @pytest.mark.asyncio
    async def test_raises_error_when_listing_snapshot_is_none(self) -> None:
        """Should raise ValueError when listing_snapshot is None for CorrelationEvaluated."""
        context = _create_context()
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()))
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            pref_snapshot=pref_snapshot,
        )

        with pytest.raises(ValueError, match="listing_snapshot is required"):
            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

    @pytest.mark.asyncio
    async def test_skips_when_notification_config_is_none(self) -> None:
        """Should skip when pref_snapshot.notification_config is None."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = SearchPrefSnapshot(
            id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            pref_name="Test Pref",
            notification_config=None,
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

            mock_service.send_job_notification_ecst.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_email_destination(self) -> None:
        """Should skip when no email address configured."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()), email="")
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

            mock_service.send_job_notification_ecst.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_score_below_threshold(self) -> None:
        """Should skip when fit_score is below threshold."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = _create_pref_snapshot(
            str(uuid.uuid4()), str(uuid.uuid4()), threshold=90, email="test@example.com"
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=80,  # Below threshold of 90
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

            mock_service.send_job_notification_ecst.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_when_score_meets_threshold(self) -> None:
        """Should send notification when score meets threshold."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = _create_pref_snapshot(
            str(uuid.uuid4()), str(uuid.uuid4()), threshold=80, email="test@example.com"
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,  # Above threshold of 80
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(return_value=[MagicMock()])
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

            mock_service.send_job_notification_ecst.assert_called_once()

    @pytest.mark.asyncio
    async def test_inline_template_is_persisted_ready_with_dedupe_identity(self) -> None:
        """An active inline template is escaped and queued with stable dedupe IDs."""
        db = create_mock_session()
        context = _create_context()
        context.require_db_session.return_value = db
        correlation_id = uuid.uuid4()
        listing_id = uuid.uuid4()
        user_id = uuid.uuid4()
        listing_snapshot = ListingNotificationSnapshot(
            id=str(listing_id),
            title="Senior <Platform> & Reliability Engineer",
            company_name="R&D Partners",
            listing_url="https://example.com/job",
        )
        pref_snapshot = _create_pref_snapshot(
            str(uuid.uuid4()),
            str(user_id),
            threshold=80,
            email="test@example.com",
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )
        context.correlation_id = str(correlation_id)

        with patch(
            "notification_service.services.messaging.repository.is_channel_supported",
            return_value=True,
        ):
            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

        persisted = db.add.call_args.args[0]
        assert persisted.status is MessageStatus.PENDING
        assert "Senior &lt;Platform&gt; &amp; Reliability Engineer" in persisted.body
        assert "R&amp;D Partners" in persisted.body
        assert persisted.correlation_id == correlation_id
        assert persisted.stored_listing_id == listing_id
        assert persisted.provider_payload == {"template_name": "job_match"}

    @pytest.mark.asyncio
    async def test_sends_when_score_equals_threshold(self) -> None:
        """Should send notification when score equals threshold."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = _create_pref_snapshot(
            str(uuid.uuid4()), str(uuid.uuid4()), threshold=80, email="test@example.com"
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=80,  # Equals threshold of 80
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(return_value=[MagicMock()])
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

            mock_service.send_job_notification_ecst.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_error_when_result_is_none_for_status_based_event(self) -> None:
        """Should raise ValueError when result is None for events requiring completed status."""
        context = _create_context()
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()), email="test@example.com")
        event = ContentGenerationCompleted(
            request_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            pref_snapshot=pref_snapshot,
        )

        with pytest.raises(ValueError, match="result is required"):
            await handle_notification_event(EVENT_TYPE_CONTENT_GENERATION_COMPLETED, event, context)

    @pytest.mark.asyncio
    async def test_skips_when_status_not_completed(self) -> None:
        """Should skip when result.status is not COMPLETED."""
        context = _create_context()
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()), email="test@example.com")
        event = ContentGenerationCompleted(
            request_id=str(uuid.uuid4()),
            listing_id=str(uuid.uuid4()),
            result=OperationOutcome(
                status=ProcessingStatus.FAILED,
                error=ErrorInfo(error_code="PROCESSING_FAILED", error_message="Processing failed"),
            ),
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CONTENT_GENERATION_COMPLETED, event, context)

            mock_service.send_job_notification_ecst.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_when_status_is_completed(self) -> None:
        """Should send notification when result.status is COMPLETED."""
        context = _create_context()
        listing_id = str(uuid.uuid4())
        listing_snapshot = _create_listing_snapshot(listing_id)
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()), email="test@example.com")
        event = ContentGenerationCompleted(
            request_id=str(uuid.uuid4()),
            listing_id=listing_id,
            result=OperationOutcome(status=ProcessingStatus.COMPLETED),
            pref_snapshot=pref_snapshot,
            listing_snapshot=listing_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(return_value=[MagicMock()])
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CONTENT_GENERATION_COMPLETED, event, context)

            mock_service.send_job_notification_ecst.assert_called_once()

    @pytest.mark.asyncio
    async def test_reraises_exception_when_send_fails(self) -> None:
        """Should re-raise exception when notification sending fails."""
        context = _create_context()
        listing_snapshot = _create_listing_snapshot(str(uuid.uuid4()))
        pref_snapshot = _create_pref_snapshot(
            str(uuid.uuid4()), str(uuid.uuid4()), threshold=80, email="test@example.com"
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=85,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(side_effect=RuntimeError("Send failed"))
            mock_service_class.return_value = mock_service

            with pytest.raises(RuntimeError, match="Send failed"):
                await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

    @pytest.mark.asyncio
    async def test_formats_subject_with_event_context(self) -> None:
        """Should format subject using event context data."""
        context = _create_context()
        listing_snapshot = ListingNotificationSnapshot(
            id=str(uuid.uuid4()),
            title="Senior Software Engineer",
            company_name="Awesome Inc",
            listing_url="https://example.com/job",
        )
        pref_snapshot = _create_pref_snapshot(
            str(uuid.uuid4()), str(uuid.uuid4()), threshold=0, email="test@example.com"
        )
        event = CorrelationEvaluated(
            correlation_id=str(uuid.uuid4()),
            fit_score=95,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )

        with patch("notification_service.services.notification_handler.NotificationService") as mock_service_class:
            mock_service = AsyncMock()
            mock_service.send_job_notification_ecst = AsyncMock(return_value=[MagicMock()])
            mock_service_class.return_value = mock_service

            await handle_notification_event(EVENT_TYPE_CORRELATION_EVALUATED, event, context)

            call_kwargs = mock_service.send_job_notification_ecst.call_args.kwargs
            params = call_kwargs["params"]
            # Subject should be formatted with listing title and company
            assert "Senior Software Engineer" in params.subject
            assert "Awesome Inc" in params.subject

    @pytest.mark.asyncio
    async def test_raises_error_when_listing_id_empty_for_content_generation(self) -> None:
        """Should raise ValueError when listing_id is empty for ContentGenerationCompleted."""
        context = _create_context()
        pref_snapshot = _create_pref_snapshot(str(uuid.uuid4()), str(uuid.uuid4()), email="test@example.com")
        event = ContentGenerationCompleted(
            request_id=str(uuid.uuid4()),
            listing_id="",
            result=OperationOutcome(status=ProcessingStatus.COMPLETED),
            pref_snapshot=pref_snapshot,
        )

        with pytest.raises(ValueError, match="listing_id is required"):
            await handle_notification_event(EVENT_TYPE_CONTENT_GENERATION_COMPLETED, event, context)

"""Tests for notification event handlers."""

from unittest.mock import MagicMock, patch

import pytest
from nohiki.common.v1 import (
    EmailDestination,
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
from nohiki_kafka_client import MessageContext


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


def _create_message_context() -> MagicMock:
    """Create a mock MessageContext."""
    context = MagicMock(spec=MessageContext)
    context.correlation_id = "test-correlation-id"
    return context


class TestHandleJobMatched:
    """Tests for handle_job_matched handler."""

    @pytest.mark.asyncio
    async def test_delegates_to_generic_handler(self) -> None:
        """Test that handle_job_matched delegates to handle_notification_event."""
        from notification_service.events.handlers import handle_job_matched

        pref_snapshot = _create_pref_snapshot("pref-1", "user-1")
        listing_snapshot = _create_listing_snapshot("listing-1")

        message = CorrelationEvaluated(
            correlation_id="corr-1",
            fit_score=85,
            listing_snapshot=listing_snapshot,
            pref_snapshot=pref_snapshot,
        )
        context = _create_message_context()

        with patch("notification_service.events.handlers.handle_notification_event") as mock_handler:
            mock_handler.return_value = None

            await handle_job_matched(message, context)

            mock_handler.assert_called_once()
            call_args = mock_handler.call_args
            assert call_args[0][0] == "nohiki.job.correlation.v1.CorrelationEvaluated"
            assert call_args[0][1] is message
            assert call_args[0][2] is context


class TestHandleContentGenerationCompleted:
    """Tests for handle_content_generation_completed handler."""

    @pytest.mark.asyncio
    async def test_delegates_to_generic_handler(self) -> None:
        """Test that handle_content_generation_completed delegates to handle_notification_event."""
        from notification_service.events.handlers import handle_content_generation_completed

        pref_snapshot = _create_pref_snapshot("pref-1", "user-1")
        listing_snapshot = _create_listing_snapshot("listing-1")

        message = ContentGenerationCompleted(
            request_id="req-1",
            listing_id="listing-1",
            template_version_id="layout-version-1",
            result=OperationOutcome(status=ProcessingStatus.COMPLETED),
            pref_snapshot=pref_snapshot,
            listing_snapshot=listing_snapshot,
        )
        context = _create_message_context()

        with patch("notification_service.events.handlers.handle_notification_event") as mock_handler:
            mock_handler.return_value = None

            await handle_content_generation_completed(message, context)

            mock_handler.assert_called_once()
            call_args = mock_handler.call_args
            assert call_args[0][0] == "nohiki.doc.content.v1.ContentGenerationCompleted"
            assert call_args[0][1] is message
            assert call_args[0][2] is context


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that function starts Kafka consumers."""
        from notification_service.events import start_event_consumer

        with (
            patch("notification_service.events.handlers.logger") as mock_logger,
            patch("notification_service.events.handlers.kafka_client") as mock_kafka,
        ):
            start_event_consumer()

            mock_logger.info.assert_called_once()
            mock_kafka.start_consumers.assert_called_once()

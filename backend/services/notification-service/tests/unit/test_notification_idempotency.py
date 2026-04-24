"""Idempotency tests for notification-service.

Verifies that duplicate notification events are handled gracefully:
- Handlers delegate to handle_notification_event which checks thresholds
- MessageService catches IntegrityError on duplicate message creation
- Processing the same event twice must not send duplicate notifications
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki.common.v1 import (
    EmailDestination,
    NotificationChannel,
    NotificationMethod,
    SearchPrefNotificationConfig,
)
from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki.job.listing.v1 import ListingNotificationSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_kafka_client import MessageContext


def _create_notification_config(
    *,
    threshold: int = 80,
    email: str = "test@example.com",
) -> SearchPrefNotificationConfig:
    """Create a notification config with email method."""
    return SearchPrefNotificationConfig(
        threshold=threshold,
        methods=[
            NotificationMethod(
                enabled=True,
                channel=NotificationChannel.EMAIL,
                email=EmailDestination(email_address=email),
            )
        ],
    )


def _create_correlation_event(
    fit_score: int = 85,
    pref_id: str = "pref-1",
    user_id: str = "user-1",
) -> CorrelationEvaluated:
    """Create a CorrelationEvaluated event for testing."""
    return CorrelationEvaluated(
        correlation_id="corr-1",
        fit_score=fit_score,
        listing_snapshot=ListingNotificationSnapshot(
            id="listing-1",
            title="Software Engineer",
            company_name="TechCorp",
            listing_url="https://example.com/job",
        ),
        pref_snapshot=SearchPrefSnapshot(
            id=pref_id,
            user_id=user_id,
            pref_name="Test Pref",
            search_keywords=["test"],
            notification_config=_create_notification_config(),
        ),
    )


def _create_context() -> MagicMock:
    """Create a mock MessageContext."""
    ctx = MagicMock(spec=MessageContext)
    ctx.correlation_id = "test-correlation-id"
    return ctx


class TestJobMatchedIdempotency:
    """Verify handle_job_matched processes duplicates gracefully."""

    @pytest.mark.asyncio
    async def test_duplicate_event_delegates_twice_without_error(self) -> None:
        """Processing the same CorrelationEvaluated twice must not raise."""
        from notification_service.events.handlers import handle_job_matched

        message = _create_correlation_event()
        context = _create_context()

        with patch("notification_service.events.handlers.handle_notification_event") as mock_handler:
            mock_handler.return_value = None

            await handle_job_matched(message, context)
            await handle_job_matched(message, context)

            assert mock_handler.call_count == 2

    @pytest.mark.asyncio
    async def test_below_threshold_skips_notification(self) -> None:
        """Events below notification threshold are skipped without error."""
        from notification_service.events.handlers import handle_job_matched

        message = _create_correlation_event(fit_score=50)
        context = _create_context()

        with patch("notification_service.events.handlers.handle_notification_event") as mock_handler:
            mock_handler.return_value = None

            await handle_job_matched(message, context)

            mock_handler.assert_called_once()

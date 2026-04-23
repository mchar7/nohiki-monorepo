"""Notification event publishing via transactional outbox pattern."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from nohiki.notification.v1 import NotificationFailed, NotificationSent
from nohiki_db_utils import OutboxEventParams, OutboxWriter
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from notification_service.core.config import settings
from notification_service.db.models import SCHEMA_NAME, MessageStatus
from notification_service.services.messaging.constants import determine_failure_cause

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from notification_service.db.models import Message

logger = get_logger(__name__)

AGGREGATE_TYPE: Final[str] = "notification"


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime has UTC timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class NotificationEventPublisher:
    """Publisher for notification lifecycle events via outbox pattern.

    Events are written to the outbox table within the caller's database
    transaction. Debezium CDC captures and publishes to Kafka after commit.
    """

    async def publish_sent(self, db: AsyncSession, message: Message) -> None:
        """Publish NotificationSent event via outbox (atomic with DB transaction).

        Call this BEFORE db.commit() to ensure atomicity with message status update.

        Args:
            db: Active database session (caller manages transaction).
            message: Message entity that was sent.

        """
        outbox = OutboxWriter(schema=SCHEMA_NAME)

        sent_at = _ensure_utc(message.sent_at) or datetime.now(UTC)
        scheduled_at = _ensure_utc(message.scheduled_at)
        correlation_id = str(message.correlation_id) if message.correlation_id else str(message.id)

        event = NotificationSent(
            metadata=create_event_metadata(settings.service_name, correlation_id),
            notification_id=str(message.id),
            channel=message.channel.to_proto(),
            recipient=message.recipient,
            sent_at=sent_at,
            retry_count=message.retry_count,
            priority=message.priority,
            user_id=str(message.user_id) if message.user_id else None,
            listing_id=str(message.stored_listing_id) if message.stored_listing_id else None,
            subject=message.subject,
            provider_name=message.provider_name,
            provider_message_id=message.provider_msg_id,
            scheduled_at=scheduled_at,
        )

        await outbox.write_event(
            db=db,
            params=OutboxEventParams(
                aggregate_type=AGGREGATE_TYPE,
                aggregate_id=str(message.id),
                event_type=Topics.NOTIFICATION_SENT,
                correlation_id=correlation_id,
            ),
            event=event,
        )

        logger.debug(
            "Wrote NOTIFICATION_SENT to outbox",
            message_id=str(message.id),
            correlation_id=correlation_id,
        )

    async def publish_failed(self, db: AsyncSession, message: Message) -> None:
        """Publish NotificationFailed event via outbox (atomic with DB transaction).

        Call this BEFORE db.commit() to ensure atomicity with message status update.

        Args:
            db: Active database session (caller manages transaction).
            message: Message entity that failed.

        """
        outbox = OutboxWriter(schema=SCHEMA_NAME)

        scheduled_at = _ensure_utc(message.scheduled_at)
        retry_at = _ensure_utc(message.retry_at)
        will_retry = message.status == MessageStatus.RETRYING and message.retry_at is not None
        correlation_id = str(message.correlation_id) if message.correlation_id else str(message.id)

        event = NotificationFailed(
            metadata=create_event_metadata(settings.service_name, correlation_id),
            notification_id=str(message.id),
            channel=message.channel.to_proto(),
            recipient=message.recipient,
            error_message=message.last_error or "Unknown error",
            retry_count=message.retry_count,
            priority=message.priority,
            failure_cause=determine_failure_cause(message.last_error),
            will_retry=will_retry,
            failed_at=datetime.now(UTC),
            user_id=str(message.user_id) if message.user_id else None,
            listing_id=str(message.stored_listing_id) if message.stored_listing_id else None,
            subject=message.subject,
            provider_name=message.provider_name,
            retry_at=retry_at,
            scheduled_at=scheduled_at,
        )

        await outbox.write_event(
            db=db,
            params=OutboxEventParams(
                aggregate_type=AGGREGATE_TYPE,
                aggregate_id=str(message.id),
                event_type=Topics.NOTIFICATION_FAILED,
                correlation_id=correlation_id,
            ),
            event=event,
        )

        logger.debug(
            "Wrote NOTIFICATION_FAILED to outbox",
            message_id=str(message.id),
            correlation_id=correlation_id,
            error=message.last_error,
        )

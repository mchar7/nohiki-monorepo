"""Notification orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nohiki.common.v1 import NotificationChannel
from nohiki_observability import get_logger

from notification_service.core.providers import is_channel_supported
from notification_service.services.messaging.channel_service import (
    raise_invalid_channels_error,
    raise_no_channels_error,
    resolve_recipient_for_channel,
    validate_channels,
)
from notification_service.services.messaging.constants import MSG_TEMPLATE_RENDERING
from notification_service.services.messaging.models import (
    BatchJobNotificationParams,
    NotificationMessageContext,
    NotificationParams,
)
from notification_service.services.messaging.repository import MessageRepository
from notification_service.services.schemas import MessageCreate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from notification_service.db.models import Message

logger = get_logger(__name__)


def _build_job_notification_template_vars(params: BatchJobNotificationParams) -> dict[str, Any]:
    """Build template variables for job notification."""
    return {
        "user_id": str(params.user_id),
        "role_id": str(params.role_id),
        "listing_id": str(params.listing_id),
        "subject": params.subject,
        "stored_listing_ids": [str(j) for j in params.stored_listing_ids],
        "listings": params.listings or [],
    }


class NotificationService:
    """Service for orchestrating notification delivery.

    This service handles the business logic of notification orchestration,
    delegating persistence to MessageRepository.
    """

    def __init__(self, repository: MessageRepository | None = None) -> None:
        """Initialize NotificationService.

        Args:
            repository: Optional MessageRepository instance. Creates new if None.

        """
        self._repository = repository or MessageRepository()

    async def enqueue_job_notification_messages(
        self,
        db: AsyncSession,
        params: NotificationParams,
    ) -> list[Message]:
        """Enqueue job notification messages for multiple channels.

        Args:
            db: Database session.
            params: Notification parameters.

        Returns:
            List of created Message entities.

        """
        messages: list[Message] = []

        for channel_str in params.channels:
            try:
                channel = NotificationChannel[channel_str.upper()]
                if not is_channel_supported(channel):
                    logger.warning("Unsupported channel for job notification", channel=channel_str)
                    continue

                recipient = None
                if channel == NotificationChannel.EMAIL:
                    recipient = params.recipient_email
                else:
                    logger.warning("Unsupported channel", channel=channel_str)
                    continue

                if not recipient:
                    logger.warning("No recipient available for channel", channel=channel_str)
                    continue

                message_create = MessageCreate(
                    user_id=params.user_id,
                    channel=channel,
                    recipient=recipient,
                    subject=f"New Listing Correlation: {params.template_vars.get('job_title', 'Unknown')}",
                    body="",
                    external_layout_id=None,
                    template_vars=params.template_vars,
                    provider_payload={},
                )

                message = await self._repository.create(db, message_create)
                messages.append(message)

                logger.info(
                    "Enqueued job notification message",
                    message_id=str(message.id),
                    channel=channel_str,
                )

            except Exception as e:
                logger.exception("Failed to enqueue job notification message", channel=channel_str, error=str(e))
                continue

        return messages

    async def send_job_notification_ecst(
        self,
        params: BatchJobNotificationParams,
        recipient_email: str,
        db: AsyncSession,
    ) -> list[Message]:
        """Send job notification using ECST data - NO cache lookups needed.

        This method is used when the recipient email is provided directly from
        the ECST snapshot in the event, eliminating the need for cache lookups.

        Args:
            params: Notification parameters including user_id, job details, etc.
            recipient_email: Account email from ECST UserNotificationSnapshot.
            db: Active database session from handler context.

        Returns:
            List of created Message records.

        Raises:
            NohikiError: If channels are invalid or message creation fails.

        """
        if not params.channels:
            raise_no_channels_error(params.user_id, params.role_id)

        validated = validate_channels(params.channels)
        if validated.has_invalid:
            raise_invalid_channels_error(validated.invalid)

        template_vars = _build_job_notification_template_vars(params)

        created_messages = await self._create_messages_for_channels(
            db,
            channels=validated.valid,
            context=NotificationMessageContext(
                user_id=params.user_id,
                user_email=recipient_email,
                subject=params.subject,
                template_vars=template_vars,
                auth_header=params.auth_header,
                template_name=params.template_name,
                rendered_body=params.rendered_body,
                correlation_id=params.correlation_id,
                stored_listing_id=params.listing_id,
            ),
        )

        logger.info(
            "Enqueued job notification (ECST)",
            user_id=str(params.user_id),
            message_count=len(created_messages),
        )

        return created_messages

    async def _create_messages_for_channels(
        self,
        db: AsyncSession,
        *,
        channels: list[NotificationChannel],
        context: NotificationMessageContext,
    ) -> list[Message]:
        """Create messages for multiple notification channels."""
        created_messages: list[Message] = []

        for channel in channels:
            recipient = resolve_recipient_for_channel(channel, context.user_email, context.user_id)
            message = await self._create_notification_message(
                db=db,
                channel=channel,
                recipient=recipient,
                context=context,
            )
            created_messages.append(message)

        return created_messages

    async def _create_notification_message(
        self,
        *,
        db: AsyncSession,
        channel: NotificationChannel,
        recipient: str,
        context: NotificationMessageContext,
    ) -> Message:
        """Create a single notification message."""
        message_create = MessageCreate(
            user_id=context.user_id,
            correlation_id=context.correlation_id,
            stored_listing_id=context.stored_listing_id,
            channel=channel,
            recipient=recipient,
            subject=context.subject,
            body=context.rendered_body if context.rendered_body is not None else MSG_TEMPLATE_RENDERING,
            external_layout_id=None,
            template_vars=context.template_vars,
            provider_payload={"template_name": context.template_name} if context.template_name else {},
        )
        return await self._repository.create(db, message_create)

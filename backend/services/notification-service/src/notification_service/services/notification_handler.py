"""Generic notification event handler using template-driven architecture.

A domain-agnostic handler that processes notification
events using the template registry for routing and rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.common.v1 import ProcessingStatus
from nohiki_observability import get_logger

from notification_service.services.messaging import (
    BatchJobNotificationParams,
    NotificationService,
)
from notification_service.services.notification_config import extract_notification_config
from notification_service.services.template_registry import (
    NotificationEvent,
    get_template_config,
    render_template,
)

if TYPE_CHECKING:
    from nohiki_kafka_client import MessageContext
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationSendParams:
    """Parameters for sending a notification."""

    template_name: str
    subject: str
    template_context: dict[str, str | int | None]
    email_address: str
    user_id: str
    correlation_id: str
    rendered_body: str = ""


async def handle_notification_event(
    event_type: str,
    event: NotificationEvent,
    context: MessageContext,
) -> None:
    """Process notification-triggering event and send notification if applicable.

    This handler:
    1. Looks up template config by event type
    2. Validates pref_snapshot exists
    3. Extracts notification_config from pref_snapshot
    4. Checks threshold (if applicable)
    5. Checks processing status (if applicable)
    6. Extracts and validates template context
    7. Sends notification

    Args:
        event_type: Fully qualified event type name
        event: The event message (CorrelationEvaluated or ContentGenerationCompleted)
        context: Kafka message context with correlation_id

    Raises:
        ValueError: If required event data is missing
        Exception: Re-raised if notification sending fails

    """
    correlation_id = context.correlation_id or ""

    # 1. Get template configuration
    template_config = get_template_config(event_type)
    if template_config is None:
        logger.warning(
            "No template registered for event type",
            event_type=event_type,
            correlation_id=correlation_id,
        )
        return

    # 2. Validate pref_snapshot exists
    pref_snapshot = event.pref_snapshot
    if pref_snapshot is None:
        msg = f"{type(event).__name__}.pref_snapshot is required but was None"
        raise ValueError(msg)

    # 3. Extract notification config from pref_snapshot
    notif_config = extract_notification_config(pref_snapshot)

    if notif_config is None:
        logger.info(
            "No notification config available, skipping",
            event_type=event_type,
            correlation_id=correlation_id,
        )
        return

    if not notif_config.email_address:
        logger.info(
            "No email destination configured, skipping",
            event_type=event_type,
            user_id=notif_config.user_id,
            pref_id=notif_config.pref_id,
            correlation_id=correlation_id,
        )
        return

    # 4. Check threshold (if applicable)
    if template_config.uses_threshold:
        score = template_config.score_extractor(event)
        if score is not None and score < notif_config.threshold:
            logger.info(
                "Score below threshold, skipping notification",
                event_type=event_type,
                score=score,
                threshold=notif_config.threshold,
                user_id=notif_config.user_id,
                correlation_id=correlation_id,
            )
            return

    # 5. Check processing status (if applicable)
    if template_config.requires_completed_status:
        result = getattr(event, "result", None)
        if result is None:
            msg = f"{type(event).__name__}.result is required but was None"
            raise ValueError(msg)
        if result.status != ProcessingStatus.COMPLETED:
            logger.info(
                "Processing not completed, skipping notification",
                event_type=event_type,
                status=result.status.name,
                correlation_id=correlation_id,
            )
            return

    # 6. Extract template context (raises ValueError if required data missing)
    template_context = template_config.context_extractor(event)
    subject = _format_subject(template_config.subject_template, template_context)
    rendered_body = render_template(template_config.template_name, template_context)

    # 7. Send notification
    db = context.require_db_session()
    await _send_notification(
        NotificationSendParams(
            template_name=template_config.template_name,
            subject=subject,
            template_context=template_context,
            email_address=notif_config.email_address,
            user_id=notif_config.user_id,
            correlation_id=correlation_id,
            rendered_body=rendered_body,
        ),
        db=db,
    )


def _format_subject(template: str, context: dict[str, str | int | None]) -> str:
    """Format a single-line subject, preserving the template on missing keys."""
    try:
        subject = template.format(**context)
    except KeyError:
        subject = template
    return " ".join(subject.splitlines())




async def _send_notification(params: NotificationSendParams, *, db: AsyncSession) -> None:
    """Send notification via MessageService.

    Args:
        params: Parameters containing template info, recipient, and context
        db: Active database session injected by Kafka handler middleware.

    Raises:
        Exception: If message sending fails

    """
    # Extract listing_id from context, fallback to user_id if not present
    listing_id_val = params.template_context.get("listing_id", params.user_id)
    listing_id_str = str(listing_id_val) if listing_id_val else params.user_id

    batch_params = BatchJobNotificationParams(
        user_id=UUID(params.user_id),
        role_id=UUID(params.user_id),  # Use user_id as role_id for generic notifications
        listing_id=UUID(listing_id_str),
        subject=params.subject,
        stored_listing_ids=[UUID(listing_id_str)],
        channels=["email"],
        listings=[dict(params.template_context)],
        template_name=params.template_name,
        rendered_body=params.rendered_body,
        correlation_id=UUID(params.correlation_id),
    )

    service = NotificationService()
    try:
        messages = await service.send_job_notification_ecst(
            params=batch_params,
            recipient_email=params.email_address,
            db=db,
        )
        logger.info(
            "Notification sent",
            template=params.template_name,
            message_count=len(messages),
            user_id=params.user_id,
            correlation_id=params.correlation_id,
        )
    except Exception:
        logger.exception(
            "Failed to send notification",
            template=params.template_name,
            user_id=params.user_id,
            correlation_id=params.correlation_id,
        )
        raise

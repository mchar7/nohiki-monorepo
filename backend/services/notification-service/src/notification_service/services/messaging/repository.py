"""Message repository for database CRUD operations."""

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from nohiki.doc.template.v1 import DocumentRenderRequested
from nohiki_db_utils import OutboxEventParams, OutboxWriter
from nohiki_fastapi_utils.errors import ErrorCode, NohikiError
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger
from nohiki_proto_google.protobuf import Struct
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from notification_service.core.config import settings
from notification_service.core.providers import is_channel_supported
from notification_service.db.models import Message, MessageStatus
from notification_service.services.messaging.constants import (
    DATABASE_ERROR_MESSAGE_CREATION,
    DATABASE_ERROR_MESSAGE_UPDATE,
    FAILED_TO_CANCEL_MESSAGE,
    FAILED_TO_RETRIEVE_MESSAGE,
    FAILED_TO_RETRIEVE_MESSAGE_STATS,
    INVALID_MESSAGE_STATUS,
    MESSAGE_NOT_FOUND,
    MSG_TEMPLATE_RENDERING,
)
from notification_service.services.schemas import (
    MessageCreate,
    MessageListResponse,
    MessageQueryParams,
    MessageStatsResponse,
    MessageUpdate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(-((0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(\+([0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
)
_MIN_LAYOUT_CONTENT_BYTES = 10
_MAX_LAYOUT_CONTENT_BYTES = 100 * 1024


def _validate_external_layout_snapshot(msg: Message) -> tuple[str, str]:
    """Return the immutable layout snapshot required by the render consumer."""
    version = msg.external_layout_version
    content = msg.external_layout_content
    if not isinstance(version, str) or not _SEMVER_PATTERN.fullmatch(version):
        raise NohikiError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="external_layout_version must be a semantic version for layout rendering",
        )
    if not isinstance(content, str):
        raise NohikiError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="external_layout_content is required for layout rendering",
        )
    content_size = len(content.encode("utf-8"))
    if content_size < _MIN_LAYOUT_CONTENT_BYTES:
        raise NohikiError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="external_layout_content is required for layout rendering",
        )
    if content_size > _MAX_LAYOUT_CONTENT_BYTES:
        raise NohikiError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"external_layout_content exceeds {_MAX_LAYOUT_CONTENT_BYTES} bytes",
        )
    return version, content


async def _enqueue_render_request(db: AsyncSession, msg: Message, data: dict[str, Any]) -> None:
    """Write a layout render request to the transactional outbox."""
    if not msg.external_layout_id:
        raise NohikiError(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="external_layout_id is required for layout rendering",
        )

    template_version, template_content = _validate_external_layout_snapshot(msg)
    msg.correlation_id = msg.correlation_id or msg.id
    event_data = DocumentRenderRequested(
        metadata=create_event_metadata(settings.service_name, str(msg.correlation_id)),
        template_id=str(msg.external_layout_id),
        template_version=template_version,
        data=Struct.from_dict(data),
        template_content=template_content,
    )
    msg.status = MessageStatus.WAITING_FOR_RENDER
    await OutboxWriter(schema=Message.__table__.schema).write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type="notification",
            aggregate_id=str(msg.id),
            event_type=Topics.DOC_TEMPLATE_RENDER_REQUESTED,
            correlation_id=str(msg.correlation_id),
        ),
        event=event_data,
    )


class MessageRepository:
    """Repository for Message entity CRUD operations."""

    async def create(
        self,
        db: AsyncSession,
        message: MessageCreate,
    ) -> Message:
        """Create a new message in the database.

        Args:
            db: Database session.
            message: Message creation data.

        Returns:
            Created Message entity.

        Raises:
            NohikiError: If channel is unsupported or database error occurs.

        """
        if not is_channel_supported(message.channel):
            error_msg = f"Channel '{message.channel}' is not supported"
            raise NohikiError(error_msg, ErrorCode.VALIDATION_ERROR)

        body = message.body
        provider_payload = message.provider_payload or {}

        needs_template_rendering = body == MSG_TEMPLATE_RENDERING and message.template_vars is not None
        if needs_template_rendering and message.external_layout_id is None:
            raise NohikiError(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="external_layout_id is required for layout rendering",
            )
        if needs_template_rendering and (not message.external_layout_version or not message.external_layout_content):
            raise NohikiError(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="external layout version and content are required for layout rendering",
            )

        if needs_template_rendering:
            body = None
            status = MessageStatus.WAITING_FOR_RENDER
        else:
            status = MessageStatus.PENDING

        # Relative to the schedule when one is given, so a deferred send gets a
        # full TTL rather than expiring before it is ever eligible.
        ttl_base = message.scheduled_at or datetime.now(UTC)
        expires_at = ttl_base + timedelta(hours=settings.message_ttl.default_ttl_hours)

        db_message = Message(
            user_id=message.user_id,
            correlation_id=message.correlation_id,
            stored_listing_id=message.stored_listing_id,
            channel=message.channel,
            recipient=message.recipient,
            subject=message.subject,
            body=body,
            external_layout_id=message.external_layout_id,
            external_layout_version=message.external_layout_version,
            external_layout_content=message.external_layout_content,
            template_vars=message.template_vars,
            provider_payload=provider_payload,
            priority=message.priority,
            scheduled_at=message.scheduled_at,
            expires_at=expires_at,
            status=status,
        )

        db.add(db_message)
        try:
            await db.flush()
            if needs_template_rendering:
                await _enqueue_render_request(db, db_message, message.template_vars or {})
            await db.commit()
            await db.refresh(db_message)

            logger.info(
                "Created new message",
                message_id=str(db_message.id),
                channel=db_message.channel,
                status=db_message.status,
            )
        except IntegrityError as e:
            await db.rollback()
            if message.stored_listing_id is not None:
                existing = await db.scalar(
                    select(Message).where(
                        Message.user_id == message.user_id,
                        Message.stored_listing_id == message.stored_listing_id,
                        Message.channel == message.channel,
                    )
                )
                if existing is not None:
                    logger.info("Notification already enqueued", message_id=str(existing.id))
                    return existing
            logger.exception("Failed to create message")
            raise NohikiError(DATABASE_ERROR_MESSAGE_CREATION, ErrorCode.DATABASE_ERROR) from e

        return db_message

    async def get_by_id(self, db: AsyncSession, message_id: UUID) -> Message:
        """Retrieve a message by its ID.

        Args:
            db: Database session.
            message_id: UUID of the message.

        Returns:
            Message entity.

        Raises:
            NohikiError: If message not found or database error.

        """
        try:
            result = await db.execute(select(Message).where(Message.id == message_id))
            message = result.scalar_one_or_none()
        except Exception as e:
            logger.exception("Failed to fetch message from database", message_id=message_id)
            raise NohikiError(FAILED_TO_RETRIEVE_MESSAGE, ErrorCode.DATABASE_ERROR) from e

        if not message:
            raise NohikiError(MESSAGE_NOT_FOUND, ErrorCode.NOT_FOUND)
        return message

    async def get_list(self, params: MessageQueryParams) -> MessageListResponse:
        """Retrieve messages with filtering and pagination.

        Args:
            params: Query parameters including filters and pagination.

        Returns:
            MessageListResponse with messages and pagination info.

        """
        query = select(Message)

        if params.user_id:
            query = query.where(Message.user_id == params.user_id)

        if params.status:
            query = query.where(Message.status == params.status)

        if params.channel:
            query = query.where(Message.channel == params.channel)

        offset = (params.page - 1) * params.size

        count_query = select(func.count()).select_from(query.alias())
        count_result = await params.db.execute(count_query)
        total = count_result.scalar()

        query = query.order_by(Message.created_at.desc()).offset(offset).limit(params.size)

        result = await params.db.execute(query)
        messages = result.scalars().all()

        return MessageListResponse(
            messages=list(messages),
            total=total or 0,
            page=params.page,
            size=params.size,
        )

    async def update(
        self,
        db: AsyncSession,
        message_id: UUID,
        message_data: MessageUpdate,
    ) -> Message:
        """Update an existing message.

        Args:
            db: Database session.
            message_id: UUID of the message to update.
            message_data: Update data.

        Returns:
            Updated Message entity.

        Raises:
            NohikiError: If message not found or database error.

        """
        try:
            existing_message = await self.get_by_id(db, message_id)

            update_data = message_data.model_dump(exclude_unset=True)
            if update_data:
                stmt = update(Message).where(Message.id == message_id).values(**update_data)
                await db.execute(stmt)
                await db.commit()
                await db.refresh(existing_message)
            else:
                logger.info("No updates to apply", message_id=str(message_id))

        except NohikiError as e:
            if e.error_code == ErrorCode.NOT_FOUND:
                raise
            await db.rollback()
            logger.exception("Failed to update message", message_id=message_id)
            raise NohikiError(DATABASE_ERROR_MESSAGE_UPDATE, ErrorCode.DATABASE_ERROR) from e
        except Exception as e:
            await db.rollback()
            logger.exception("Failed to update message", message_id=message_id)
            raise NohikiError(DATABASE_ERROR_MESSAGE_UPDATE, ErrorCode.DATABASE_ERROR) from e
        else:
            logger.info("Updated message", message_id=str(message_id))
            return existing_message

    async def cancel(self, db: AsyncSession, message_id: UUID) -> Message:
        """Cancel a pending message.

        Args:
            db: Database session.
            message_id: UUID of the message to cancel.

        Returns:
            Cancelled Message entity.

        Raises:
            NohikiError: If message not found, already sent/failed, or database error.

        """
        message = await self.get_by_id(db, message_id)

        if message.status in {MessageStatus.SENT, MessageStatus.FAILED}:
            error_msg = f"{INVALID_MESSAGE_STATUS} {message.status}"
            raise NohikiError(error_msg, ErrorCode.VALIDATION_ERROR)

        try:
            message.status = MessageStatus.CANCELLED
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.exception("Failed to cancel message", message_id=message_id)
            raise NohikiError(FAILED_TO_CANCEL_MESSAGE, ErrorCode.DATABASE_ERROR) from e

        logger.info("Cancelled message", message_id=str(message_id))
        return message

    async def get_stats(self, db: AsyncSession) -> MessageStatsResponse:
        """Retrieve message statistics by status.

        Args:
            db: Database session.

        Returns:
            MessageStatsResponse with counts by status.

        Raises:
            NohikiError: If database error occurs.

        """
        try:
            result = await db.execute(select(Message.status, func.count(Message.id)).group_by(Message.status))
            rows = result.all()

            status_counts: dict[str, int] = {status.value: 0 for status in MessageStatus}

            total = 0
            for status, count in rows:
                status_counts[status.value] = count
                total += count

            return MessageStatsResponse(
                total=total,
                by_status=status_counts,
            )

        except Exception as e:
            logger.exception("Failed to get message stats")
            raise NohikiError(FAILED_TO_RETRIEVE_MESSAGE_STATS, ErrorCode.DATABASE_ERROR) from e

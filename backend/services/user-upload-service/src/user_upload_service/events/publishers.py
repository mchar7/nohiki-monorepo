"""Event publishing functions for attachment lifecycle events."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from nohiki.common.v1 import EntityTimestamps
from nohiki.user.upload.v1 import UploadCreated, UploadDeleted, UploadSnapshot
from nohiki_db_utils import OutboxEventParams
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from user_upload_service.core.config import get_settings
from user_upload_service.db.models import _CONTENT_TYPE_TO_MIME

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

    from user_upload_service.db.models import Upload

logger = get_logger(__name__)
settings = get_settings()

AGGREGATE_TYPE = "upload"


class _BatchOutboxWriter(Protocol):
    async def write_events(
        self,
        db: AsyncSession | None,
        entries: Sequence[tuple[OutboxEventParams, UploadDeleted]],
    ) -> list[UUID]:
        """Write multiple upload events to the outbox table."""
        ...


def _build_upload_snapshot(attachment: Upload) -> UploadSnapshot:
    """Build UploadSnapshot from attachment model."""
    created_at = attachment.created_at
    updated_at = attachment.updated_at

    if created_at is None or updated_at is None:
        msg = "attachment created_at and updated_at must be set"
        raise ValueError(msg)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)

    timestamps = EntityTimestamps(created_at=created_at, updated_at=updated_at)

    return UploadSnapshot(
        id=str(attachment.id),
        user_id=str(attachment.user_id),
        name=attachment.name,
        content_type=_CONTENT_TYPE_TO_MIME.get(attachment.content_type, "application/octet-stream"),
        file_size=attachment.file_size,
        content_hash=attachment.content_hash,
        storage_key=attachment.storage_key,
        document_category=attachment.category,
        timestamps=timestamps,
    )


async def publish_attachment_created_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    attachment: Upload,
) -> None:
    """Publish upload created event with UploadSnapshot (ECST)."""
    snapshot = _build_upload_snapshot(attachment)
    event = UploadCreated(
        metadata=create_event_metadata(settings.service_name, str(attachment.id)),
        upload_id=str(attachment.id),
        user_id=str(attachment.user_id),
        upload_snapshot=snapshot,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(attachment.id),
            event_type=Topics.USER_UPLOAD_CREATED,
        ),
        event=event,
    )
    logger.info("Published upload created event", upload_id=str(attachment.id))


async def publish_attachment_deleted_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    upload_id: UUID,
    user_id: UUID,
) -> None:
    """Publish upload deleted event."""
    event = UploadDeleted(
        metadata=create_event_metadata(settings.service_name, str(upload_id)),
        upload_id=str(upload_id),
        user_id=str(user_id),
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(upload_id),
            event_type=Topics.USER_UPLOAD_DELETED,
        ),
        event=event,
    )
    logger.info("Published upload deleted event", upload_id=str(upload_id))


async def publish_attachment_deleted_batch(
    db: AsyncSession,
    outbox: OutboxWriter,
    attachments: Sequence[Upload],
) -> None:
    """Publish a batch of upload deleted events."""
    if not attachments:
        return

    await cast("_BatchOutboxWriter", outbox).write_events(
        db=db,
        entries=[
            (
                OutboxEventParams(
                    aggregate_type=AGGREGATE_TYPE,
                    aggregate_id=str(attachment.id),
                    event_type=Topics.USER_UPLOAD_DELETED,
                ),
                UploadDeleted(
                    metadata=create_event_metadata(settings.service_name, str(attachment.id)),
                    upload_id=str(attachment.id),
                    user_id=str(attachment.user_id),
                ),
            )
            for attachment in attachments
        ],
    )

    logger.info("Published upload deleted events", count=len(attachments))

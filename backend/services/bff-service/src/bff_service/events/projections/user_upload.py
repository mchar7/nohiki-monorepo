"""User upload domain projection handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from nohiki.user.upload.v1 import UploadCreated, UploadDeleted
from nohiki_common_exceptions import ValidationError
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from bff_service.core.kafka import kafka_client
from bff_service.db.models import AttachmentProjection
from bff_service.events.projections._constants import projection_priority_group_id

logger = get_logger(__name__)


@kafka_client.message_handler(
    Topics.USER_UPLOAD_CREATED, UploadCreated, group_id=projection_priority_group_id, preserve_partition_order=False
)
@kafka_client.with_db_session()
async def handle_attachment_created(message: UploadCreated, context: MessageContext) -> None:
    """Handle upload created event - create attachment projection."""
    snapshot = message.upload_snapshot
    if snapshot is None:
        raise ValidationError(
            field_name="upload_snapshot",
            constraint="UploadCreated.upload_snapshot is required",
        )

    session = context.require_db_session()
    stmt = (
        insert(AttachmentProjection)
        .values(
            id=UUID(snapshot.id),
            user_id=UUID(snapshot.user_id),
            filename=snapshot.name,
            content_type=snapshot.content_type,
            file_size=snapshot.file_size,
            storage_key=snapshot.storage_key,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    logger.info("Upload projection created", upload_id=snapshot.id)


@kafka_client.message_handler(
    Topics.USER_UPLOAD_DELETED, UploadDeleted, group_id=projection_priority_group_id, preserve_partition_order=False
)
@kafka_client.with_db_session()
async def handle_attachment_deleted(message: UploadDeleted, context: MessageContext) -> None:
    """Handle upload deleted event - remove attachment projection."""
    session = context.require_db_session()
    stmt = delete(AttachmentProjection).where(AttachmentProjection.id == UUID(message.upload_id))
    await session.execute(stmt)
    logger.info("Upload projection deleted", upload_id=message.upload_id)

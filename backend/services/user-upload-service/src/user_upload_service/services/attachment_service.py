"""Upload service for file storage operations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.common.v1 import ContentType
from nohiki_fastapi_utils.errors import NotFoundError
from nohiki_observability import get_logger
from nohiki_s3_client import S3Client, S3ObjectNotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from user_upload_service.db.models import Upload

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UploadMetadataInput:
    """Input data for creating upload metadata."""

    upload_id: UUID
    user_id: UUID
    storage_key: str
    filename: str
    content_type: ContentType
    file_size: int
    content_hash: str


async def _delete_object_idempotently(s3_client: S3Client, storage_key: str) -> None:
    """Delete an object, treating an already-missing object as success."""
    try:
        await s3_client.delete_object(storage_key)
    except S3ObjectNotFoundError:
        logger.info("S3 object already absent during deletion", storage_key=storage_key)


async def get_attachment_by_id(db: AsyncSession, upload_id: UUID) -> Upload:
    """Get attachment by ID."""
    attachment = await db.get(Upload, upload_id)
    if not attachment or attachment.is_deleted:
        raise NotFoundError(resource="Upload", identifier=str(upload_id))
    return attachment


async def get_attachment_by_id_or_none(db: AsyncSession, upload_id: UUID) -> Upload | None:
    """Get attachment by ID, returning None if not found.

    Args:
        db: Database session.
        upload_id: Upload ID to look up.

    Returns:
        Upload if found and not deleted, None otherwise.

    """
    attachment = await db.get(Upload, upload_id)
    if not attachment or attachment.is_deleted:
        return None
    return attachment


async def exists_by_id(db: AsyncSession, upload_id: UUID) -> bool:
    """Check if an upload record exists by PK, including soft-deleted records.

    Used for idempotency checks on create commands: a retry after deletion
    must not re-insert a row with the same PK.

    Args:
        db: Database session.
        upload_id: Upload ID to look up.

    Returns:
        True if a record exists (regardless of is_deleted), False otherwise.

    """
    return await db.get(Upload, upload_id) is not None


async def create_metadata(db: AsyncSession, data: UploadMetadataInput) -> Upload:
    """Create upload metadata record (file already uploaded to S3 by BFF).

    Args:
        db: Database session.
        data: Upload metadata input containing all required fields.

    Returns:
        Created Upload record.

    """
    attachment = Upload(
        id=data.upload_id,
        user_id=data.user_id,
        storage_key=data.storage_key,
        name=data.filename,
        content_type=data.content_type,
        file_size=data.file_size,
        content_hash=data.content_hash,
    )
    db.add(attachment)
    await db.flush()
    await db.refresh(attachment)

    logger.info(
        "Created upload metadata",
        upload_id=str(attachment.id),
        user_id=str(data.user_id),
        filename=data.filename,
        size=data.file_size,
    )
    return attachment


async def list_user_attachments(db: AsyncSession, user_id: UUID) -> list[Upload]:
    """List all attachments for a user."""
    result = await db.execute(
        select(Upload).where(Upload.user_id == user_id, Upload.is_deleted.is_(False)).order_by(Upload.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_attachment(
    db: AsyncSession,
    s3_client: S3Client,
    upload_id: UUID,
) -> Upload:
    """Delete attachment from S3 and mark as deleted in database.

    Args:
        db: Database session.
        s3_client: S3 client instance.
        upload_id: Upload ID to delete.

    Returns:
        The deleted Upload record.

    """
    attachment = await get_attachment_by_id(db, upload_id)

    # Do not commit the soft-delete/outbox transaction until object deletion
    # succeeds. Kafka redelivery retries transient storage failures.
    await _delete_object_idempotently(s3_client, attachment.storage_key)

    # Mark as deleted (soft delete for audit trail)
    attachment.is_deleted = True
    await db.flush()

    logger.info("Deleted attachment", upload_id=str(upload_id))
    return attachment


async def delete_user_attachments(
    db: AsyncSession,
    s3_client: S3Client,
    user_id: UUID,
) -> list[Upload]:
    """Delete all attachments for a user. Called when user is deleted.

    Args:
        db: Database session.
        s3_client: S3 client instance.
        user_id: User ID whose attachments to delete.

    Returns:
        List of soft-deleted Upload records.

    """
    attachments = await list_user_attachments(db, user_id)

    if attachments:
        if len(attachments) == 1:
            await _delete_object_idempotently(s3_client, attachments[0].storage_key)
        else:
            async with asyncio.TaskGroup() as tg:
                for attachment in attachments:
                    tg.create_task(_delete_object_idempotently(s3_client, attachment.storage_key))
        for attachment in attachments:
            attachment.is_deleted = True

        await db.flush()

    logger.info("Deleted all attachments for user", user_id=str(user_id), count=len(attachments))
    return attachments

"""Kafka event handlers for user-upload-service.

Importing this module registers all Kafka handlers via decorator side effects.
"""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import ContentType
from nohiki.user.auth.v1 import AccountDeleted
from nohiki.user.upload.v1 import UploadCreateRequested, UploadDeleteRequested
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from nohiki_s3_client import S3Client

from user_upload_service.core.config import get_settings
from user_upload_service.core.kafka import kafka_client
from user_upload_service.events.publishers import (
    publish_attachment_created_event,
    publish_attachment_deleted_batch,
    publish_attachment_deleted_event,
)
from user_upload_service.services import attachment_service
from user_upload_service.services.attachment_service import UploadMetadataInput

logger = get_logger(__name__)
settings = get_settings()
_s3_client = S3Client(settings.s3)

command_group_id = f"{settings.kafka.consumer_group}-commands"

_MIME_TO_CONTENT_TYPE: dict[str, ContentType] = {
    "application/pdf": ContentType.PDF,
    "application/msword": ContentType.DOC,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ContentType.DOCX,
    "text/plain": ContentType.TXT,
    "application/rtf": ContentType.RTF,
    "text/html": ContentType.HTML,
    "text/markdown": ContentType.MARKDOWN,
    "application/json": ContentType.JSON,
    "image/png": ContentType.PNG,
    "image/jpeg": ContentType.JPEG,
    "image/webp": ContentType.WEBP,
}


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCOUNT_DELETED,
    AccountDeleted,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_user_deleted(message: AccountDeleted, context: MessageContext) -> None:
    """Clean up attachments when a user is deleted."""
    if not message.user_id:
        msg = "AccountDeleted.user_id is required but was empty"
        raise ValueError(msg)

    user_id = UUID(message.user_id)
    logger.info("Processing user deletion for attachments", user_id=str(user_id))

    deleted = await attachment_service.delete_user_attachments(context.require_db_session(), _s3_client, user_id)

    db = context.require_db_session()
    outbox = context.require_outbox()
    await publish_attachment_deleted_batch(db, outbox, deleted)

    logger.info("Cleaned up attachments for deleted user", user_id=str(user_id), count=len(deleted))


@kafka_client.message_handler(Topics.USER_UPLOAD_CREATE_REQUESTED, UploadCreateRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_upload_create_requested(message: UploadCreateRequested, context: MessageContext) -> None:
    """Handle upload create command - creates metadata record for S3-uploaded file."""
    request_id: str = message.request_id
    user_id: UUID = UUID(message.user_id)

    logger.info(
        "Processing upload create command",
        request_id=request_id,
        user_id=str(user_id),
        storage_key=message.storage_key,
        filename=message.filename,
    )

    db = context.require_db_session()
    upload_id = UUID(request_id)
    if await attachment_service.exists_by_id(db, upload_id):
        logger.info("Upload already exists (idempotent skip)", upload_id=str(upload_id))
        return

    content_type_value = _MIME_TO_CONTENT_TYPE.get(message.content_type)
    if content_type_value is None:
        msg = f"Unsupported upload content type: {message.content_type!r}"
        raise ValueError(msg)

    file_size = int(message.file_size)
    if not 0 < file_size <= settings.upload.max_size_bytes:
        msg = f"Upload size must be between 1 and {settings.upload.max_size_bytes} bytes"
        raise ValueError(msg)

    metadata_input = UploadMetadataInput(
        upload_id=upload_id,
        user_id=user_id,
        storage_key=message.storage_key,
        filename=message.filename,
        content_type=content_type_value,
        file_size=file_size,
        content_hash=message.content_hash,
    )
    attachment = await attachment_service.create_metadata(db, metadata_input)
    await publish_attachment_created_event(db, context.require_outbox(), attachment)

    logger.info("Upload create command completed", request_id=request_id, upload_id=str(upload_id))


@kafka_client.message_handler(Topics.USER_UPLOAD_DELETE_REQUESTED, UploadDeleteRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_upload_delete_requested(message: UploadDeleteRequested, context: MessageContext) -> None:
    """Handle upload delete command - deletes metadata and S3 object."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    upload_id = UUID(message.upload_id)

    logger.info(
        "Processing upload delete command",
        request_id=request_id,
        upload_id=str(upload_id),
    )

    db = context.require_db_session()
    attachment = await attachment_service.get_attachment_by_id_or_none(db, upload_id)
    if not attachment:
        logger.info("Upload not found, already deleted", upload_id=str(upload_id))
        return

    if attachment.user_id != user_id:
        logger.warning("User does not own upload", user_id=str(user_id), upload_id=str(upload_id))
        return

    await attachment_service.delete_attachment(db, _s3_client, upload_id)
    await publish_attachment_deleted_event(db, context.require_outbox(), upload_id, user_id)

    logger.info("Upload delete command completed", request_id=request_id, upload_id=str(upload_id))


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

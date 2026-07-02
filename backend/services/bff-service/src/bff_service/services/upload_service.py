"""Upload service: direct object-storage uploads with authoritative completion validation.

Upload lifecycle:
1. ``initiate_upload`` generates a provider-specific presigned PUT URL.
2. The client uploads directly to the configured object store.
3. ``complete_upload_command`` validates stored size and content type, computes SHA-256,
   then publishes ``USER_UPLOAD_CREATE_REQUESTED``.
4. user-upload-service processes the command and publishes ``USER_UPLOAD_CREATED`` CDC.
5. The BFF projection handler upserts ``AttachmentProjection`` from the CDC event.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from nohiki.user.upload.v1 import UploadCreateRequested, UploadDeleteRequested
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger
from nohiki_s3_client import S3PresignedPutConstraints, get_s3_client
from uuid_utils.compat import uuid7

from bff_service.core.config import get_settings
from bff_service.core.kafka import kafka_client

logger = get_logger(__name__)
settings = get_settings()

_PRESIGNED_URL_EXPIRY_SECONDS: int = 3600
_STORAGE_KEY_PREFIX: str = "user-uploads"


_FILE_SIZE_MISMATCH_MSG: str = "Uploaded file size does not match declared size"
_CONTENT_TYPE_MISMATCH_MSG: str = "Uploaded content type does not match declared content type"


@dataclass(frozen=True, slots=True)
class CompleteUploadInput:
    """Bundled expectations for authoritative upload completion validation."""

    upload_id: UUID
    filename: str
    content_type: str
    file_size: int


def _build_storage_key(user_id: UUID, upload_id: str, filename: str) -> str:
    """Build the deterministic object-storage key for an upload."""
    return f"{_STORAGE_KEY_PREFIX}/{user_id}/{upload_id}/{filename}"


@dataclass(frozen=True, slots=True)
class UploadInitiation:
    """Provider-neutral direct-upload instructions."""

    upload_url: str
    upload_headers: dict[str, str]


class UploadService:
    """CQRS upload service for direct uploads and Kafka command publishing.

    Presigned PUT constraints are enforced by S3 when supported. Azure Blob SAS
    grants create/write access to the exact blob; expected size and content type
    remain authoritative inputs to completion validation.
    """

    async def initiate_upload(
        self,
        user_id: UUID,
        upload_id: str,
        filename: str,
        content_type: str,
        file_size: int,
    ) -> UploadInitiation:
        """Generate a provider-specific presigned PUT URL for a direct upload.

        S3 signs supported content-type and content-length constraints into the
        request. Azure Blob SAS cannot bind those request properties, so they are
        treated as expectations and validated authoritatively at completion.

        Args:
            user_id: Owner of the upload.
            upload_id: Pre-generated UUIDv7 identifying this upload.
            filename: Original file name used in the storage key.
            content_type: Expected MIME type for completion validation.
            file_size: Expected byte length for completion validation.

        Returns:
            Provider-neutral URL and required request headers.
        """
        storage_key = _build_storage_key(user_id, upload_id, filename)
        s3 = get_s3_client(settings.s3)
        url: str = await s3.generate_presigned_url(
            key=storage_key,
            expires_in=_PRESIGNED_URL_EXPIRY_SECONDS,
            http_method="PUT",
            put_constraints=S3PresignedPutConstraints(
                content_type=content_type,
                content_length=file_size,
            ),
        )
        logger.info(
            "Presigned upload URL generated",
            user_id=str(user_id),
            upload_id=upload_id,
            filename=filename,
        )
        return UploadInitiation(upload_url=url, upload_headers=s3.required_upload_headers())

    async def complete_upload_command(self, user_id: UUID, data: CompleteUploadInput) -> None:
        """Validate the stored upload and publish its create command.

        Stored size and content type must match the declared expectations. The
        object is then read with the declared size as a hard bound, its exact
        byte count is rechecked, and SHA-256 is computed before publication.

        Args:
            user_id: Owner of the upload.
            data: Expected upload metadata; SHA-256 is computed server-side.

        Raises:
            S3ObjectNotFoundError: If the client did not upload the object.
            ValueError: If stored size or content type differs from expectations.
        """
        upload_id_str = str(data.upload_id)
        storage_key = _build_storage_key(user_id, upload_id_str, data.filename)

        s3 = get_s3_client(settings.s3)
        object_metadata = await s3.head_object(storage_key)

        if object_metadata.content_length != data.file_size:
            msg = f"{_FILE_SIZE_MISMATCH_MSG}: expected {data.file_size}, got {object_metadata.content_length}"
            raise ValueError(msg)
        if object_metadata.content_type != data.content_type:
            msg = f"{_CONTENT_TYPE_MISMATCH_MSG}: expected {data.content_type}, got {object_metadata.content_type}"
            raise ValueError(msg)

        content = await s3.get_object(storage_key, max_bytes=data.file_size)

        if len(content) != data.file_size:
            msg = f"{_FILE_SIZE_MISMATCH_MSG}: expected {data.file_size}, got {len(content)}"
            raise ValueError(msg)

        content_hash = hashlib.sha256(content).hexdigest()

        event = UploadCreateRequested(
            metadata=create_event_metadata(settings.service_name, upload_id_str),
            request_id=upload_id_str,
            user_id=str(user_id),
            storage_key=storage_key,
            filename=data.filename,
            content_type=data.content_type,
            file_size=data.file_size,
            content_hash=content_hash,
        )

        await kafka_client.publish(Topics.USER_UPLOAD_CREATE_REQUESTED, event, key=upload_id_str)

        logger.info(
            "Upload create command published",
            user_id=str(user_id),
            upload_id=upload_id_str,
            filename=data.filename,
            content_hash=content_hash,
        )

    async def delete_upload_command(self, user_id: UUID, upload_id: UUID) -> str:
        """Publish upload delete command.

        Args:
            user_id: Owner of the upload.
            upload_id: Upload to delete.

        Returns:
            Request ID for tracking.

        """
        request_id = str(uuid7())

        event = UploadDeleteRequested(
            metadata=create_event_metadata(settings.service_name, request_id),
            request_id=request_id,
            user_id=str(user_id),
            upload_id=str(upload_id),
        )

        await kafka_client.publish(Topics.USER_UPLOAD_DELETE_REQUESTED, event, key=request_id)

        logger.info(
            "Upload delete command published",
            user_id=str(user_id),
            upload_id=str(upload_id),
            request_id=request_id,
        )
        return request_id

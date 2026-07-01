"""Attachments API routes: direct object-storage file management via Kafka CQRS."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from nohiki_db_utils import paginate_query
from nohiki_fastapi_utils import PaginatedResponse, PaginationParams
from nohiki_observability import get_logger
from nohiki_s3_client import (
    S3Client,
    S3ConnectionError,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
    get_s3_client,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils.compat import uuid7

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.core.config import get_settings
from bff_service.core.db import get_async_db
from bff_service.db.models import AttachmentProjection
from bff_service.services.upload_service import CompleteUploadInput, UploadService

logger = get_logger(__name__)

router = APIRouter()

_PRESIGNED_URL_EXPIRY_SECONDS: int = 3600
_MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB
_ATTACHMENT_RESPONSE_CONCURRENCY: int = 8


def _get_upload_service() -> UploadService:
    """Dependency: return singleton UploadService."""
    return UploadService()


def _get_s3_client() -> S3Client:
    """Dependency: return singleton S3Client from service settings."""
    return get_s3_client(get_settings().s3)


class InitiateUploadRequest(BaseModel):
    """Request to initiate a file upload."""

    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=100)
    file_size: int = Field(..., gt=0, le=_MAX_FILE_SIZE_BYTES)


class InitiateUploadResponse(BaseModel):
    """Response with a provider-specific direct-upload URL."""

    upload_id: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_in: int = _PRESIGNED_URL_EXPIRY_SECONDS


class CompleteUploadRequest(BaseModel):
    """Metadata sent by the client after uploading to object storage.

    The BFF re-derives the storage key, validates the stored object, and
    computes its content hash; no hash is accepted from the client.
    """

    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=100)
    file_size: int = Field(..., gt=0, le=_MAX_FILE_SIZE_BYTES)


class AttachmentResponse(BaseModel):
    """Attachment metadata from the BFF projection."""

    id: str
    user_id: str
    filename: str
    content_type: str
    file_size: int
    download_url: str | None = None
    created_at: datetime | None = None


async def _attachment_to_response(a: AttachmentProjection, s3_client: S3Client) -> AttachmentResponse:
    """Convert an AttachmentProjection ORM row to an API response model.

    Generates a provider-specific download URL when the projection has a
    ``storage_key``. If URL generation fails, ``download_url`` is set to
    ``None`` and a warning is logged rather than propagating the error.

    Args:
        a: ORM projection row to convert.
        s3_client: S3 client used to generate the presigned download URL.

    Returns:
        ``AttachmentResponse`` with ``download_url`` populated when possible.

    """
    download_url: str | None = None
    if storage_key := (a.storage_key or "").strip():
        try:
            download_url = await s3_client.generate_presigned_url(
                key=storage_key,
                expires_in=_PRESIGNED_URL_EXPIRY_SECONDS,
                http_method="GET",
            )
        except S3ConnectionError:
            logger.warning(
                "Failed to generate presigned download URL",
                storage_key=storage_key,
            )
    return AttachmentResponse(
        id=str(a.id),
        user_id=str(a.user_id),
        filename=a.filename,
        content_type=a.content_type,
        file_size=a.file_size,
        download_url=download_url,
        created_at=a.created_at,
    )


async def _write_attachment_response(
    index: int,
    attachment: AttachmentProjection,
    s3_client: S3Client,
    semaphore: asyncio.Semaphore,
    responses: dict[int, AttachmentResponse],
) -> None:
    """Populate one slot in the attachment response list."""
    async with semaphore:
        responses[index] = await _attachment_to_response(attachment, s3_client)


async def _attachments_to_responses(
    attachments: Sequence[AttachmentProjection],
    s3_client: S3Client,
) -> list[AttachmentResponse]:
    """Map attachment projections to responses with bounded concurrency."""
    if not attachments:
        return []

    responses: dict[int, AttachmentResponse] = {}
    semaphore = asyncio.Semaphore(_ATTACHMENT_RESPONSE_CONCURRENCY)

    async with asyncio.TaskGroup() as task_group:
        for index, attachment in enumerate(attachments):
            task_group.create_task(
                _write_attachment_response(index, attachment, s3_client, semaphore, responses),
            )

    return [responses[index] for index in range(len(attachments))]


@router.get("")
async def list_attachments(
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    pagination: Annotated[PaginationParams, Query()],
    s3_client: Annotated[S3Client, Depends(_get_s3_client)],
) -> PaginatedResponse[AttachmentResponse]:
    """List all attachments for the current user from projection."""
    logger.debug("Listing attachments", user_id=str(user_id))
    query = select(AttachmentProjection).where(AttachmentProjection.user_id == user_id)
    result = await paginate_query(db, query, offset=pagination.offset, limit=pagination.page_size)
    items = await _attachments_to_responses(result.items, s3_client)
    return PaginatedResponse[AttachmentResponse].create(
        items=items,
        total=result.total,
        params=pagination,
    )


@router.post("/initiate", response_model=InitiateUploadResponse)
async def initiate_upload(
    data: InitiateUploadRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[UploadService, Depends(_get_upload_service)],
) -> InitiateUploadResponse:
    """Generate a provider-specific direct-upload URL.

    The client uploads to object storage, then calls ``complete_upload`` to
    validate and register the attachment.
    """
    upload_id = str(uuid7())
    initiation = await service.initiate_upload(
        user_id=user_id,
        upload_id=upload_id,
        filename=data.filename,
        content_type=data.content_type,
        file_size=data.file_size,
    )
    logger.info(
        "Upload initiated",
        user_id=str(user_id),
        upload_id=upload_id,
        filename=data.filename,
    )
    return InitiateUploadResponse(
        upload_id=upload_id,
        upload_url=initiation.upload_url,
        upload_headers=initiation.upload_headers,
    )


@router.post("/{upload_id}/complete", status_code=status.HTTP_200_OK)
async def complete_upload(
    upload_id: UUID,
    data: CompleteUploadRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[UploadService, Depends(_get_upload_service)],
) -> dict[str, str]:
    """Validate an object-store upload and register the attachment.

    The BFF reads the uploaded object through the internal storage endpoint,
    computes SHA-256, and publishes ``USER_UPLOAD_CREATE_REQUESTED``. No
    content hash is accepted from the client.
    """
    try:
        await service.complete_upload_command(
            user_id,
            CompleteUploadInput(
                upload_id=upload_id,
                filename=data.filename,
                content_type=data.content_type,
                file_size=data.file_size,
            ),
        )
    except S3ObjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded file not found in storage. Ensure the file was uploaded before calling complete.",
        ) from None
    except (S3ObjectTooLargeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None
    logger.info("Upload completed", user_id=str(user_id), upload_id=str(upload_id))
    return {"status": "completed", "upload_id": str(upload_id)}


@router.get("/{upload_id}", response_model=AttachmentResponse)
async def get_attachment(
    upload_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    s3_client: Annotated[S3Client, Depends(_get_s3_client)],
) -> AttachmentResponse:
    """Get attachment metadata from projection by ID."""
    logger.debug("Getting attachment", user_id=str(user_id), upload_id=str(upload_id))
    stmt = select(AttachmentProjection).where(
        AttachmentProjection.id == upload_id,
        AttachmentProjection.user_id == user_id,
    )
    result = await db.execute(stmt)
    if attachment := result.scalar_one_or_none():
        return await _attachment_to_response(attachment, s3_client)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")


@router.delete("/{upload_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_attachment(
    upload_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[UploadService, Depends(_get_upload_service)],
) -> dict[str, str]:
    """Delete an attachment by publishing a Kafka delete command (CQRS async)."""
    request_id = await service.delete_upload_command(user_id=user_id, upload_id=upload_id)
    logger.info(
        "Attachment delete command published",
        user_id=str(user_id),
        upload_id=str(upload_id),
        request_id=request_id,
    )
    return {"status": "accepted", "request_id": request_id}

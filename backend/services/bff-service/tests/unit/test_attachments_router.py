"""Unit tests for BFF attachments router."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from bff_service.db.models import AttachmentProjection
from fastapi import HTTPException
from nohiki_db_utils.testing import create_mock_session
from nohiki_s3_client import S3Client, S3ConnectionError, S3ObjectNotFoundError, S3ObjectTooLargeError
from pytest_mock import MockerFixture


def _make_attachment_projection(attachment_id: uuid.UUID, user_id: uuid.UUID) -> AttachmentProjection:
    mock = MagicMock(spec=AttachmentProjection)
    mock.id = attachment_id
    mock.user_id = user_id
    mock.filename = "test.pdf"
    mock.content_type = "application/pdf"
    mock.file_size = 1024
    mock.storage_key = f"user-uploads/{user_id}/{attachment_id}/test.pdf"
    mock.created_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    return cast("AttachmentProjection", mock)


def _make_scalar_all(items: list[Any]) -> MagicMock:
    result = MagicMock()
    result.all = lambda: items
    return result


def _make_mock_s3_client(presigned_url: str = "https://s3.example.com/presigned?sig=abc") -> AsyncMock:
    """Create a mock S3Client with generate_presigned_url pre-configured.

    Args:
        presigned_url: URL returned by generate_presigned_url.

    Returns:
        AsyncMock configured as S3Client.
    """
    mock = AsyncMock(spec=S3Client)
    mock.generate_presigned_url.return_value = presigned_url
    return mock


@pytest.mark.asyncio
async def test_list_attachments_returns_projections(mocker: MockerFixture) -> None:
    from bff_service.api.routers.attachments import list_attachments
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    attachment_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)
    mock_s3 = _make_mock_s3_client()

    attachment = _make_attachment_projection(attachment_id, user_id)

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([attachment])
    mock_db.execute.side_effect = [count_result, mock_result]

    result = await list_attachments(user_id, mock_db, pagination, mock_s3)

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].filename == "test.pdf"


@pytest.mark.asyncio
async def test_list_attachments_returns_empty_when_none(mocker: MockerFixture) -> None:
    from bff_service.api.routers.attachments import list_attachments
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)
    mock_s3 = _make_mock_s3_client()

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 0
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([])
    mock_db.execute.side_effect = [count_result, mock_result]

    result = await list_attachments(user_id, mock_db, pagination, mock_s3)

    assert result.total == 0
    assert result.items == []


@pytest.mark.asyncio
async def test_list_attachments_preserves_order_with_concurrent_mapping(mocker: MockerFixture) -> None:
    from bff_service.api.routers.attachments import list_attachments
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    attachment_one = _make_attachment_projection(uuid.uuid4(), user_id)
    attachment_two = _make_attachment_projection(uuid.uuid4(), user_id)
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)
    mock_s3 = _make_mock_s3_client()

    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release = asyncio.Event()

    async def generate_presigned_url(*, key: str, expires_in: int, http_method: str) -> str:
        del expires_in, http_method
        if not first_started.is_set():
            first_started.set()
            await second_started.wait()
        else:
            second_started.set()
            await first_started.wait()
        await release.wait()
        return f"https://s3.example.com/{key}"

    mock_s3.generate_presigned_url.side_effect = generate_presigned_url

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 2
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([attachment_one, attachment_two])
    mock_db.execute.side_effect = [count_result, mock_result]

    async def release_when_second_starts() -> None:
        await asyncio.wait_for(second_started.wait(), timeout=1)
        release.set()

    release_task = asyncio.create_task(release_when_second_starts())
    try:
        result = await asyncio.wait_for(list_attachments(user_id, mock_db, pagination, mock_s3), timeout=1)
    finally:
        if release_task.done():
            await release_task
        else:
            release_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await release_task

    assert [item.id for item in result.items] == [str(attachment_one.id), str(attachment_two.id)]
    assert [item.download_url for item in result.items] == [
        f"https://s3.example.com/{attachment_one.storage_key}",
        f"https://s3.example.com/{attachment_two.storage_key}",
    ]


@pytest.mark.asyncio
async def test_initiate_upload_returns_presigned_url() -> None:
    from bff_service.api.routers.attachments import InitiateUploadRequest, initiate_upload
    from bff_service.services.upload_service import UploadInitiation, UploadService

    user_id = uuid.uuid4()
    data = InitiateUploadRequest(filename="resume.pdf", content_type="application/pdf", file_size=2048)

    mock_service = MagicMock(spec=UploadService)
    mock_service.initiate_upload = AsyncMock(
        return_value=UploadInitiation(
            upload_url="http://localhost:9002/nohiki-attachments/key?X-Amz-Signature=abc",
            upload_headers={},
        )
    )

    result = await initiate_upload(data, user_id, mock_service)

    assert result.upload_id is not None
    assert "localhost:9002" in result.upload_url
    assert result.expires_in == 3600
    assert result.upload_headers == {}
    mock_service.initiate_upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_upload_returns_success() -> None:
    from bff_service.api.routers.attachments import CompleteUploadRequest, complete_upload
    from bff_service.services.upload_service import UploadService

    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    data = CompleteUploadRequest(filename="resume.pdf", content_type="application/pdf", file_size=2048)

    mock_service = MagicMock(spec=UploadService)
    mock_service.complete_upload_command = AsyncMock(return_value=None)

    result = await complete_upload(upload_id, data, user_id, mock_service)

    assert result["status"] == "completed"
    assert result["upload_id"] == str(upload_id)
    mock_service.complete_upload_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_upload_raises_422_when_s3_object_not_found() -> None:
    from bff_service.api.routers.attachments import CompleteUploadRequest, complete_upload
    from bff_service.services.upload_service import UploadService

    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    data = CompleteUploadRequest(filename="resume.pdf", content_type="application/pdf", file_size=2048)

    mock_service = MagicMock(spec=UploadService)
    mock_service.complete_upload_command = AsyncMock(side_effect=S3ObjectNotFoundError("user-uploads/key"))

    with pytest.raises(HTTPException) as exc_info:
        await complete_upload(upload_id, data, user_id, mock_service)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_complete_upload_raises_422_on_size_mismatch() -> None:
    from bff_service.api.routers.attachments import CompleteUploadRequest, complete_upload
    from bff_service.services.upload_service import UploadService

    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    data = CompleteUploadRequest(filename="resume.pdf", content_type="application/pdf", file_size=9999)

    mock_service = MagicMock(spec=UploadService)
    mock_service.complete_upload_command = AsyncMock(
        side_effect=ValueError("Uploaded file size does not match declared size: expected 9999, got 42")
    )

    with pytest.raises(HTTPException) as exc_info:
        await complete_upload(upload_id, data, user_id, mock_service)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_complete_upload_maps_bounded_read_overflow_to_422() -> None:
    """An S3 body that exceeds the declared read cap surfaces as a client error."""
    from bff_service.api.routers.attachments import CompleteUploadRequest, complete_upload
    from bff_service.services.upload_service import UploadService

    upload_id = uuid.uuid4()
    data = CompleteUploadRequest(filename="resume.pdf", content_type="application/pdf", file_size=2048)
    mock_service = MagicMock(spec=UploadService)
    mock_service.complete_upload_command = AsyncMock(side_effect=S3ObjectTooLargeError("user-uploads/key", 2048))

    with pytest.raises(HTTPException) as exc_info:
        await complete_upload(upload_id, data, uuid.uuid4(), mock_service)

    assert exc_info.value.status_code == 422
    assert "exceeds" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_get_attachment_raises_404(mocker: MockerFixture) -> None:
    from bff_service.api.routers.attachments import get_attachment

    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_s3 = _make_mock_s3_client()

    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await get_attachment(upload_id, user_id, mock_db, mock_s3)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_attachment_returns_accepted() -> None:
    from bff_service.api.routers.attachments import delete_attachment
    from bff_service.services.upload_service import UploadService

    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()

    mock_service = MagicMock(spec=UploadService)
    mock_service.delete_upload_command = AsyncMock(return_value="req-id-123")

    result = await delete_attachment(upload_id, user_id, mock_service)

    assert result["status"] == "accepted"
    assert result["request_id"] == "req-id-123"


def test_attachment_to_response_is_callable() -> None:
    """Smoke test: _attachment_to_response is importable and callable."""
    from bff_service.api.routers.attachments import _attachment_to_response

    assert callable(_attachment_to_response)


@pytest.mark.asyncio
async def test_attachment_to_response_with_storage_key() -> None:
    """_attachment_to_response returns a populated download_url when storage_key is set."""
    from bff_service.api.routers.attachments import _attachment_to_response

    user_id = uuid.uuid4()
    attachment_id = uuid.uuid4()
    attachment = _make_attachment_projection(attachment_id, user_id)
    expected_url = "https://s3.example.com/user-uploads/key?sig=abc"
    mock_s3 = _make_mock_s3_client(presigned_url=expected_url)

    response = await _attachment_to_response(attachment, mock_s3)

    assert response.id == str(attachment_id)
    assert response.user_id == str(user_id)
    assert response.filename == "test.pdf"
    assert response.content_type == "application/pdf"
    assert response.file_size == 1024
    assert response.download_url == expected_url
    assert response.created_at == datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    mock_s3.generate_presigned_url.assert_awaited_once_with(
        key=f"user-uploads/{user_id}/{attachment_id}/test.pdf",
        expires_in=3600,
        http_method="GET",
    )


@pytest.mark.asyncio
async def test_attachment_to_response_without_storage_key() -> None:
    """_attachment_to_response returns download_url=None when storage_key is absent."""
    from bff_service.api.routers.attachments import _attachment_to_response

    user_id = uuid.uuid4()
    attachment_id = uuid.uuid4()
    mock = MagicMock(spec=AttachmentProjection, storage_key=None)
    mock.id = attachment_id
    mock.user_id = user_id
    mock.filename = "test.pdf"
    mock.content_type = "application/pdf"
    mock.file_size = 1024
    mock.created_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
    attachment = cast("AttachmentProjection", mock)
    mock_s3 = _make_mock_s3_client()

    response = await _attachment_to_response(attachment, mock_s3)

    assert response.download_url is None
    mock_s3.generate_presigned_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_attachment_to_response_s3_error_returns_none() -> None:
    """_attachment_to_response gracefully returns download_url=None when S3 raises."""
    from bff_service.api.routers.attachments import _attachment_to_response

    user_id = uuid.uuid4()
    attachment_id = uuid.uuid4()
    attachment = _make_attachment_projection(attachment_id, user_id)
    mock_s3 = AsyncMock(spec=S3Client)
    mock_s3.generate_presigned_url.side_effect = S3ConnectionError("S3 unavailable")

    response = await _attachment_to_response(attachment, mock_s3)

    assert response.download_url is None

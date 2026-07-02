import hashlib
import uuid
from typing import Any

import pytest
from nohiki_s3_client import S3ObjectMetadata, S3PresignedPutConstraints
from pytest_mock import MockerFixture


def _import_upload_service() -> type[Any]:
    from bff_service.services.upload_service import UploadService

    return UploadService


def _metadata(content: bytes, content_type: str = "application/pdf") -> S3ObjectMetadata:
    return S3ObjectMetadata(
        content_length=len(content),
        content_type=content_type,
        etag="test-etag",
        metadata={},
        checksum_sha256=None,
    )


@pytest.mark.asyncio
async def test_complete_upload_command_fetches_s3_and_publishes_with_computed_hash(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """complete_upload_command fetches S3 object, computes SHA-256, and publishes event."""
    from bff_service.services.upload_service import CompleteUploadInput

    service = _import_upload_service()()
    content = b"resume content bytes"
    expected_hash = hashlib.sha256(content).hexdigest()

    mock_s3 = mocker.AsyncMock()
    mock_s3.head_object = mocker.AsyncMock(return_value=_metadata(content))
    mock_s3.get_object = mocker.AsyncMock(return_value=content)

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.upload_service.kafka_client", mock_kafka)
    monkeypatch.setattr("bff_service.services.upload_service.get_s3_client", lambda _: mock_s3)

    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    filename = "resume.pdf"

    data = CompleteUploadInput(
        upload_id=upload_id,
        filename=filename,
        content_type="application/pdf",
        file_size=len(content),
    )

    await service.complete_upload_command(user_id, data)

    expected_storage_key = f"user-uploads/{user_id}/{upload_id}/{filename}"
    mock_s3.head_object.assert_awaited_once_with(expected_storage_key)
    mock_s3.get_object.assert_awaited_once_with(expected_storage_key, max_bytes=len(content))

    topic, event = mock_publish.call_args.args
    assert topic == "user-upload.cmd.create-requested.v1"
    assert mock_publish.call_args.kwargs.get("key") == str(upload_id)
    assert event.user_id == str(user_id)
    assert event.filename == filename
    assert event.content_type == "application/pdf"
    assert event.file_size == len(content)
    assert event.storage_key == expected_storage_key
    assert event.content_hash == expected_hash


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("actual_size_delta", "actual_content_type", "message"),
    [
        pytest.param(1, "application/pdf", "size", id="oversized-object"),
        pytest.param(0, "text/plain", "content type", id="content-type-mismatch"),
    ],
)
async def test_complete_upload_rejects_metadata_mismatch_before_body_read(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    actual_size_delta: int,
    actual_content_type: str,
    message: str,
) -> None:
    """Untrusted S3 metadata must be rejected before downloading or publishing."""
    from bff_service.services.upload_service import CompleteUploadInput

    content = b"actual bytes"
    metadata = S3ObjectMetadata(
        content_length=len(content) + actual_size_delta,
        content_type=actual_content_type,
        etag="test-etag",
        metadata={},
        checksum_sha256=None,
    )
    mock_s3 = mocker.AsyncMock()
    mock_s3.head_object = mocker.AsyncMock(return_value=metadata)
    mock_s3.get_object = mocker.AsyncMock()
    mock_publish = mocker.AsyncMock()
    monkeypatch.setattr("bff_service.services.upload_service.get_s3_client", lambda _: mock_s3)
    monkeypatch.setattr(
        "bff_service.services.upload_service.kafka_client",
        mocker.MagicMock(publish=mock_publish),
    )
    data = CompleteUploadInput(
        upload_id=uuid.uuid4(),
        filename="resume.pdf",
        content_type="application/pdf",
        file_size=len(content),
    )

    with pytest.raises(ValueError, match=message):
        await _import_upload_service()().complete_upload_command(uuid.uuid4(), data)

    mock_s3.get_object.assert_not_awaited()
    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_upload_rejects_short_bounded_read_without_publishing(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A truncated body after a valid HEAD must never create an attachment event."""
    from bff_service.services.upload_service import CompleteUploadInput

    declared = b"complete object"
    mock_s3 = mocker.AsyncMock()
    mock_s3.head_object = mocker.AsyncMock(return_value=_metadata(declared))
    mock_s3.get_object = mocker.AsyncMock(return_value=declared[:-1])
    mock_publish = mocker.AsyncMock()
    monkeypatch.setattr("bff_service.services.upload_service.get_s3_client", lambda _: mock_s3)
    monkeypatch.setattr(
        "bff_service.services.upload_service.kafka_client",
        mocker.MagicMock(publish=mock_publish),
    )
    data = CompleteUploadInput(
        upload_id=uuid.uuid4(),
        filename="resume.pdf",
        content_type="application/pdf",
        file_size=len(declared),
    )

    with pytest.raises(ValueError, match="size"):
        await _import_upload_service()().complete_upload_command(uuid.uuid4(), data)

    mock_s3.get_object.assert_awaited_once()
    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_initiate_upload_passes_expected_content_constraints(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Initiation passes declared MIME type and length to the storage provider."""
    mock_s3 = mocker.AsyncMock()
    mock_s3.generate_presigned_url = mocker.AsyncMock(return_value="https://s3.test/upload")
    mock_s3.required_upload_headers = mocker.Mock(return_value={"x-ms-blob-type": "BlockBlob"})
    monkeypatch.setattr("bff_service.services.upload_service.get_s3_client", lambda _: mock_s3)
    user_id = uuid.uuid4()
    upload_id = str(uuid.uuid4())

    result = await _import_upload_service()().initiate_upload(
        user_id,
        upload_id,
        "resume.pdf",
        "application/pdf",
        4096,
    )

    assert result.upload_url == "https://s3.test/upload"
    assert result.upload_headers == {"x-ms-blob-type": "BlockBlob"}
    mock_s3.generate_presigned_url.assert_awaited_once_with(
        key=f"user-uploads/{user_id}/{upload_id}/resume.pdf",
        expires_in=3600,
        http_method="PUT",
        put_constraints=S3PresignedPutConstraints(
            content_type="application/pdf",
            content_length=4096,
        ),
    )
    mock_s3.required_upload_headers.assert_called_once_with()


@pytest.mark.asyncio
async def test_delete_upload_command_publishes(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _import_upload_service()()
    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.upload_service.kafka_client", mock_kafka)
    user_id = uuid.uuid4()
    upload_id = uuid.uuid4()

    rid = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.upload_service.uuid7", lambda: rid)

    request_id = await service.delete_upload_command(user_id, upload_id)

    assert request_id == str(rid)
    topic, event = mock_publish.call_args.args
    assert topic == "user-upload.cmd.delete-requested.v1"
    assert mock_publish.call_args.kwargs.get("key") == str(rid)
    assert event.upload_id == str(upload_id)

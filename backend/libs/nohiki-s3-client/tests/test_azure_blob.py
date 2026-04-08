"""Azure Blob backend contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from nohiki_s3_client import ObjectStorageProvider, S3PresignedPutConstraints, S3Settings
from nohiki_s3_client.client import S3Client
from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
    S3PermissionError,
)
from pydantic import SecretStr


def azure_settings(**changes: object) -> S3Settings:
    values: dict[str, object] = {
        "provider": ObjectStorageProvider.AZURE_BLOB,
        "endpoint": "https://account.blob.core.windows.net",
        "public_url": "https://cdn.example.test",
        "access_key": SecretStr("account"),
        "secret_key": SecretStr("key"),
        "bucket": "container",
    }
    values.update(changes)
    return S3Settings.model_validate(values)


def service_with_blob() -> tuple[MagicMock, MagicMock]:
    blob = MagicMock()
    service = MagicMock()
    service.close = AsyncMock()
    service.get_blob_client.return_value = blob
    return service, blob


async def test_provider_dispatch_and_service_closure() -> None:
    service, blob = service_with_blob()
    blob.exists = AsyncMock(return_value=True)
    with patch("nohiki_s3_client.client.BlobServiceClient", return_value=service) as factory:
        client = S3Client(azure_settings())
        assert await client.object_exists("folder/item") is True
    factory.assert_called_once_with(account_url="https://account.blob.core.windows.net", credential="key")
    service.get_blob_client.assert_called_once_with("container", "folder/item")
    service.close.assert_awaited_once()


@pytest.mark.parametrize(("size", "data"), [(5, b"12345"), (4, b"12345")])
async def test_bounded_ranged_download(size: int, data: bytes) -> None:
    service, blob = service_with_blob()
    blob.get_blob_properties = AsyncMock(return_value=SimpleNamespace(size=size))
    downloader = MagicMock(readall=AsyncMock(return_value=data))
    blob.download_blob = AsyncMock(return_value=downloader)
    with patch("nohiki_s3_client.client.BlobServiceClient", return_value=service):
        client = S3Client(azure_settings())
        if size > 4 or len(data) > 4:
            with pytest.raises(S3ObjectTooLargeError):
                await client.get_object("item", max_bytes=4)
        else:
            await client.get_object("item", max_bytes=4)
    if size <= 4:
        blob.download_blob.assert_awaited_once_with(offset=0, length=5)


async def test_metadata_normalization_and_checksum_absence() -> None:
    service, blob = service_with_blob()
    blob.get_blob_properties = AsyncMock(
        return_value=SimpleNamespace(
            size=7,
            etag='"etag"',
            metadata={"Mixed-Key": 9},
            content_settings=SimpleNamespace(content_type="text/plain"),
        )
    )
    with patch("nohiki_s3_client.client.BlobServiceClient", return_value=service):
        metadata = await S3Client(azure_settings()).head_object("item")
    assert metadata.content_length == 7
    assert metadata.content_type == "text/plain"
    assert metadata.etag == '"etag"'
    assert metadata.metadata == {"mixed-key": "9"}
    assert metadata.checksum_sha256 is None


async def test_upload_delete_list_and_container_access() -> None:
    service, blob = service_with_blob()
    blob.upload_blob = AsyncMock()
    blob.delete_blob = AsyncMock()
    container = MagicMock()
    container.get_container_properties = AsyncMock()
    container.list_blobs.return_value = _blob_names("one", "two", "ignored")
    service.get_container_client.return_value = container
    with patch("nohiki_s3_client.client.BlobServiceClient", return_value=service):
        client = S3Client(azure_settings())
        await client.put_object("item", b"body", "text/plain", {"a": "b"})
        await client.delete_object("item")
        assert await client.check_bucket_access()
        assert await client.list_objects_sample(2) == ["one", "two"]
    kwargs = blob.upload_blob.await_args
    assert kwargs is not None
    assert kwargs.kwargs["length"] == 4
    assert kwargs.kwargs["overwrite"] is True
    assert kwargs.kwargs["metadata"] == {"a": "b"}
    assert kwargs.kwargs["content_settings"].content_type == "text/plain"
    blob.delete_blob.assert_awaited_once_with(delete_snapshots="include")
    container.list_blobs.assert_called_once_with(results_per_page=2)


async def _blob_names(*names: str) -> AsyncIterator[SimpleNamespace]:
    for name in names:
        yield SimpleNamespace(name=name)


def _http_error(message: str, status_code: int, reason: str) -> HttpResponseError:
    error = HttpResponseError(message)
    error.status_code = status_code
    error.reason = reason
    return error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ResourceNotFoundError("missing"), S3ObjectNotFoundError),
        (_http_error("forbidden", 403, "Forbidden"), S3PermissionError),
        (_http_error("broken", 500, "Broken"), S3ConnectionError),
    ],
)
async def test_azure_error_mapping(error: HttpResponseError, expected: type[Exception]) -> None:
    service, blob = service_with_blob()
    blob.exists = AsyncMock(side_effect=error)
    with patch("nohiki_s3_client.client.BlobServiceClient", return_value=service), pytest.raises(expected):
        await S3Client(azure_settings()).object_exists("item")


@pytest.mark.parametrize(
    ("method", "read", "create", "write"), [("GET", True, False, False), ("PUT", False, True, False)]
)
async def test_sas_is_https_bounded_and_has_exact_permissions(
    method: str, *, read: bool, create: bool, write: bool
) -> None:
    with patch("nohiki_s3_client.client.generate_blob_sas", return_value="sig=token") as generate:
        url = await S3Client(azure_settings()).generate_presigned_url("folder/a b", 60, method)
    assert url == "https://cdn.example.test/container/folder/a%20b?sig=token"
    call = generate.call_args.kwargs
    assert call["protocol"] == "https"
    assert call["permission"].read is read
    assert call["permission"].create is create
    assert call["permission"].write is write
    remaining = (call["expiry"] - datetime.now(UTC)).total_seconds()
    assert 55 <= remaining <= 60


async def test_azure_put_accepts_api_constraints_with_exact_write_sas() -> None:
    """Azure accepts expected constraints while completion validates them authoritatively."""
    constraints = S3PresignedPutConstraints(
        content_type="text/plain",
        content_length=7,
        checksum_sha256="digest",
    )

    with patch("nohiki_s3_client.client.generate_blob_sas", return_value="sig=token") as generate:
        url = await S3Client(azure_settings()).generate_presigned_url(
            "folder/item",
            expires_in=60,
            http_method="PUT",
            put_constraints=constraints,
        )

    assert url == "https://cdn.example.test/container/folder/item?sig=token"
    call = generate.call_args.kwargs
    assert call["protocol"] == "https"
    assert call["permission"].read is False
    assert call["permission"].create is True
    assert call["permission"].write is False
    remaining = (call["expiry"] - datetime.now(UTC)).total_seconds()
    assert 55 <= remaining <= 60


@pytest.mark.parametrize("key", ["", "nul\x00key", "é" * 513], ids=["empty", "nul", "utf8-too-long"])
async def test_azure_rejects_invalid_object_keys(key: str) -> None:
    with pytest.raises(ValueError, match="object key must be non-empty, NUL-free"):
        await S3Client(azure_settings()).object_exists(key)


async def test_azure_rejects_invalid_operation_boundaries() -> None:
    client = S3Client(azure_settings())

    with pytest.raises(ValueError, match="max_bytes must be greater than zero"):
        await client.get_object("item", max_bytes=0)
    with pytest.raises(ValueError, match="max_keys must be between"):
        await client.list_objects_sample(0)
    with pytest.raises(ValueError, match="expires_in must be between"):
        await client.generate_presigned_url("item", expires_in=0)
    with pytest.raises(ValueError, match="http_method must be GET or PUT"):
        await client.generate_presigned_url("item", http_method="DELETE")


class FakeDefaultAzureCredential:
    """Controllable workload-identity credential used at the Azure SDK boundary."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


async def test_workload_identity_presign_uses_delegation_key_and_closes_resources() -> None:
    service, _ = service_with_blob()
    service.get_user_delegation_key = AsyncMock(return_value="delegation-key")

    with (
        patch("nohiki_s3_client.client.DefaultAzureCredential", FakeDefaultAzureCredential),
        patch("nohiki_s3_client.client.BlobServiceClient", return_value=service) as service_factory,
        patch("nohiki_s3_client.client.generate_blob_sas", return_value="sig=token") as generate,
    ):
        url = await S3Client(azure_settings(access_key=None, secret_key=None, public_url="")).generate_presigned_url(
            "folder/item", expires_in=60
        )

    assert url == "https://account.blob.core.windows.net/container/folder/item?sig=token"
    credential = service_factory.call_args.kwargs["credential"]
    assert isinstance(credential, FakeDefaultAzureCredential)
    assert credential.closed
    service.close.assert_awaited_once()
    service.get_user_delegation_key.assert_awaited_once()
    call = generate.call_args.kwargs
    assert call["account_name"] == "account"
    assert call["user_delegation_key"] == "delegation-key"
    assert "account_key" not in call


@pytest.mark.parametrize(
    ("endpoint", "message"),
    [
        ("http://account.blob.core.windows.net", "endpoint must use HTTPS"),
        ("https://?container", "endpoint must include an account hostname"),
    ],
)
def test_azure_rejects_unsafe_or_hostless_service_endpoints(endpoint: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        S3Client(azure_settings(endpoint=endpoint))


def test_direct_upload_headers_are_provider_specific() -> None:
    azure = S3Client(azure_settings())
    s3 = S3Client(S3Settings(bucket="bucket"))

    assert azure.required_upload_headers() == {"x-ms-blob-type": "BlockBlob"}
    assert s3.required_upload_headers() == {}


def test_s3_remains_default_backend() -> None:
    settings = S3Settings(bucket="bucket")
    assert settings.provider is ObjectStorageProvider.S3
    client = S3Client(settings)
    assert client._backend.__class__.__name__ == "_S3Backend"

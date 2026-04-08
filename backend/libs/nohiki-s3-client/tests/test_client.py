"""Tests for S3 client."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from nohiki_s3_client import S3PresignedPutConstraints, S3Settings
from nohiki_s3_client.client import S3Client
from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
    S3PermissionError,
)
from pydantic import SecretStr

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from nohiki_s3_client.client import _S3Backend


def _s3_backend(client: S3Client) -> _S3Backend:
    """Return the S3 backend selected by the S3 settings fixtures."""
    return cast("_S3Backend", client._backend)


def _create_client_error(code: str, message: str = "Error") -> ClientError:
    """Create a botocore ClientError for testing."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="TestOperation",
    )


@pytest.fixture
def s3_settings() -> S3Settings:
    """Create S3Settings for testing."""
    return S3Settings(
        endpoint="http://localhost:9000",
        access_key=SecretStr("test-access-key"),
        secret_key=SecretStr("test-secret-key"),
        bucket="test-bucket",
        region="us-east-1",
        connect_timeout=10,
        read_timeout=30,
    )


@pytest.fixture
def s3_settings_no_credentials() -> S3Settings:
    """Create S3Settings without credentials (IAM role mode)."""
    return S3Settings(
        endpoint="",
        access_key=None,
        secret_key=None,
        bucket="test-bucket",
        region="us-east-1",
        connect_timeout=10,
        read_timeout=30,
    )


class TestS3ClientInit:
    """Tests for S3Client initialization."""

    def test_init_creates_session(self, s3_settings: S3Settings) -> None:
        """Test that S3Client creates a session on init."""
        client = S3Client(s3_settings)
        assert client._settings is s3_settings
        assert _s3_backend(client)._session is not None

    def test_init_with_no_credentials(self, s3_settings_no_credentials: S3Settings) -> None:
        """Test that S3Client can be initialized without credentials."""
        client = S3Client(s3_settings_no_credentials)
        assert client._settings is s3_settings_no_credentials
        assert _s3_backend(client)._session is not None


class FragmentedBody:
    """Bounded async body that may return short reads before EOF."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    async def read(self, amt: int) -> bytes:
        await asyncio.sleep(0)
        chunk = next(self._chunks, b"")
        assert len(chunk) <= amt
        return chunk

    async def __aenter__(self) -> FragmentedBody:
        """Enter the bounded response-body context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Mark the response body closed when leaving its context."""
        self.closed = True


class TestS3ClientGetObject:
    """Tests for S3Client.get_object."""

    async def test_get_object_success(self, s3_settings: S3Settings) -> None:
        """Test successful object retrieval."""

        class MockBody:
            chunks = iter([b"test content", b""])

            async def read(self, amt: int) -> bytes:
                await asyncio.sleep(0)
                chunk = next(self.chunks)
                assert len(chunk) <= amt
                return chunk

            async def __aenter__(self) -> MockBody:
                return self

            async def __aexit__(self, *args: object) -> None:
                await asyncio.sleep(0)

        mock_response = {"Body": MockBody()}
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(return_value=mock_response)

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.get_object("test-key")

        assert result == b"test content"
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="test-key",
        )

    async def test_get_object_supports_aiohttp_response_body(self, s3_settings: S3Settings) -> None:
        """Use the bounded content reader when aiobotocore exposes ClientResponse."""

        class MockContent:
            chunks = iter([b"test content", b""])

            async def read(self, amt: int) -> bytes:
                chunk = next(self.chunks)
                assert len(chunk) <= amt
                return chunk

        class MockResponseBody:
            content = MockContent()

            async def read(self) -> bytes:
                msg = "unbounded response read must not be used"
                raise AssertionError(msg)

            async def __aenter__(self) -> MockResponseBody:
                return self

            async def __aexit__(self, *args: object) -> None:
                await asyncio.sleep(0)

        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(return_value={"Body": MockResponseBody()})

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)
        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.get_object("test-key")

        assert result == b"test content"

    @pytest.mark.parametrize(
        ("chunks", "max_bytes", "expected"),
        [
            ([b"short ", b"reads", b""], 32, b"short reads"),
            ([b"123", b"45", b""], 5, b"12345"),
        ],
        ids=["multiple-short-reads", "exact-limit"],
    )
    async def test_get_object_accumulates_fragmented_body(
        self,
        s3_settings: S3Settings,
        chunks: list[bytes],
        max_bytes: int,
        expected: bytes,
    ) -> None:
        """Accumulate short reads through EOF, including the exact limit."""
        body = FragmentedBody(chunks)
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(return_value={"Body": body})

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)
        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.get_object("fragmented-key", max_bytes=max_bytes)

        assert result == expected
        assert body.closed

    async def test_get_object_rejects_fragmented_body_over_limit(self, s3_settings: S3Settings) -> None:
        """Reject max_bytes + 1 even when it arrives across short reads."""
        body = FragmentedBody([b"123", b"456", b""])
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(return_value={"Body": body})

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)
        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ObjectTooLargeError) as exc_info,
        ):
            await client.get_object("fragmented-key", max_bytes=5)

        assert exc_info.value.max_bytes == 5
        assert body.closed

    async def test_get_object_not_found(self, s3_settings: S3Settings) -> None:
        """Test get_object raises S3ObjectNotFoundError for missing objects."""
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(side_effect=_create_client_error("NoSuchKey"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ObjectNotFoundError),
        ):
            await client.get_object("missing-key")

    async def test_get_object_permission_denied(self, s3_settings: S3Settings) -> None:
        """Test get_object raises S3PermissionError for access denied."""
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(side_effect=_create_client_error("AccessDenied"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3PermissionError),
        ):
            await client.get_object("protected-key")

    async def test_get_object_connection_error(self, s3_settings: S3Settings) -> None:
        """Test get_object raises S3ConnectionError for connection failures."""
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(side_effect=Exception("Connection failed"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.get_object("test-key")


class TestS3ClientPutObject:
    """Tests for S3Client.put_object."""

    async def test_put_object_success(self, s3_settings: S3Settings) -> None:
        """Test successful object upload."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            await client.put_object(
                key="test-key",
                data=b"test content",
                content_type="text/plain",
                metadata={"user": "test"},
            )

        mock_s3.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="test-key",
            Body=b"test content",
            ContentType="text/plain",
            Metadata={"user": "test"},
        )

    async def test_put_object_permission_denied(self, s3_settings: S3Settings) -> None:
        """Test put_object raises S3PermissionError for access denied."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=_create_client_error("AccessDenied"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3PermissionError),
        ):
            await client.put_object("test-key", b"content")

    async def test_put_object_generic_client_error(self, s3_settings: S3Settings) -> None:
        """put_object raises S3ConnectionError for non-access-denied ClientError."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=_create_client_error("InternalError", "Server error"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.put_object("test-key", b"content")


class TestS3ClientGetObjectGenericClientError:
    """Tests for get_object generic ClientError fallthrough."""

    async def test_get_object_generic_client_error(self, s3_settings: S3Settings) -> None:
        """get_object raises S3ConnectionError for unrecognized ClientError codes."""
        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(side_effect=_create_client_error("InternalError", "Server error"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.get_object("test-key")


class TestS3ClientDeleteObject:
    """Tests for S3Client.delete_object."""

    async def test_delete_object_success(self, s3_settings: S3Settings) -> None:
        """Test successful object deletion."""
        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            await client.delete_object("test-key")

        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="test-key",
        )

    async def test_delete_object_permission_denied(self, s3_settings: S3Settings) -> None:
        """Test delete_object raises S3PermissionError for access denied."""
        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=_create_client_error("AccessDenied"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3PermissionError),
        ):
            await client.delete_object("protected-key")

    async def test_delete_object_client_error(self, s3_settings: S3Settings) -> None:
        """Test delete_object raises S3ConnectionError for other ClientErrors."""
        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=_create_client_error("InternalError"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.delete_object("test-key")

    async def test_delete_object_generic_exception(self, s3_settings: S3Settings) -> None:
        """Test delete_object raises S3ConnectionError for generic exceptions."""
        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=Exception("Network failure"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.delete_object("test-key")


class TestS3ClientObjectExists:
    """Tests for S3Client.object_exists."""

    async def test_object_exists_true(self, s3_settings: S3Settings) -> None:
        """Test object_exists returns True for existing objects."""
        mock_s3 = AsyncMock()
        mock_s3.head_object = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.object_exists("test-key")

        assert result is True

    async def test_object_exists_false(self, s3_settings: S3Settings) -> None:
        """Test object_exists returns False for missing objects."""
        mock_s3 = AsyncMock()
        mock_s3.head_object = AsyncMock(side_effect=_create_client_error("404"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.object_exists("missing-key")

        assert result is False

    async def test_object_exists_permission_denied(self, s3_settings: S3Settings) -> None:
        """Test object_exists raises S3PermissionError for access denied."""
        mock_s3 = AsyncMock()
        mock_s3.head_object = AsyncMock(side_effect=_create_client_error("AccessDenied"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3PermissionError),
        ):
            await client.object_exists("protected-key")

    async def test_object_exists_client_error(self, s3_settings: S3Settings) -> None:
        """Test object_exists raises S3ConnectionError for other ClientErrors."""
        mock_s3 = AsyncMock()
        mock_s3.head_object = AsyncMock(side_effect=_create_client_error("ServiceUnavailable"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.object_exists("test-key")

    async def test_object_exists_generic_exception(self, s3_settings: S3Settings) -> None:
        """Test object_exists raises S3ConnectionError for generic exceptions."""
        mock_s3 = AsyncMock()
        mock_s3.head_object = AsyncMock(side_effect=Exception("Timeout"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.object_exists("test-key")


class TestS3ClientCheckBucketAccess:
    """Tests for S3Client.check_bucket_access."""

    async def test_check_bucket_access_success(self, s3_settings: S3Settings) -> None:
        """Test successful bucket access check."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.check_bucket_access()

        assert result is True

    async def test_check_bucket_access_permission_denied(self, s3_settings: S3Settings) -> None:
        """Test check_bucket_access raises S3PermissionError for access denied."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=_create_client_error("403"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3PermissionError),
        ):
            await client.check_bucket_access()

    async def test_check_bucket_access_client_error(self, s3_settings: S3Settings) -> None:
        """Test check_bucket_access raises S3ConnectionError for other ClientErrors."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=_create_client_error("InternalError"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.check_bucket_access()

    async def test_check_bucket_access_generic_exception(self, s3_settings: S3Settings) -> None:
        """Test check_bucket_access raises S3ConnectionError for generic exceptions."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=Exception("Connection refused"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.check_bucket_access()


class TestS3ClientListObjectsSample:
    """Tests for S3Client.list_objects_sample."""

    async def test_list_objects_sample_success(self, s3_settings: S3Settings) -> None:
        """Test successful object listing."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(return_value={"Contents": [{"Key": "file1.txt"}, {"Key": "file2.txt"}]})

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.list_objects_sample(max_keys=2)

        assert result == ["file1.txt", "file2.txt"]

    async def test_list_objects_sample_empty(self, s3_settings: S3Settings) -> None:
        """Test object listing returns empty list for empty bucket."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(return_value={})

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.list_objects_sample()

        assert result == []

    async def test_list_objects_sample_permission_denied(self, s3_settings: S3Settings) -> None:
        """Test list_objects_sample raises S3PermissionError for access denied."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(side_effect=_create_client_error("AccessDenied"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3PermissionError),
        ):
            await client.list_objects_sample()

    async def test_list_objects_sample_client_error(self, s3_settings: S3Settings) -> None:
        """Test list_objects_sample raises S3ConnectionError for other ClientErrors."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(side_effect=_create_client_error("Throttling"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.list_objects_sample()

    async def test_list_objects_sample_generic_exception(self, s3_settings: S3Settings) -> None:
        """Test list_objects_sample raises S3ConnectionError for generic exceptions."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(side_effect=Exception("DNS resolution failed"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.list_objects_sample()


class TestS3ClientGeneratePresignedUrl:
    """Tests for S3Client.generate_presigned_url."""

    async def test_generate_presigned_url_get(self, s3_settings: S3Settings) -> None:
        """Test presigned URL generation for GET."""
        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(return_value="https://s3.example.com/presigned")

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            result = await client.generate_presigned_url("test-key", expires_in=3600)

        assert result == "https://s3.example.com/presigned"
        mock_s3.generate_presigned_url.assert_called_once_with(
            ClientMethod="get_object",
            Params={"Bucket": "test-bucket", "Key": "test-key"},
            ExpiresIn=3600,
        )

    async def test_generate_presigned_url_put(self, s3_settings: S3Settings) -> None:
        """Test presigned URL generation for PUT."""
        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(return_value="https://s3.example.com/presigned")

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            await client.generate_presigned_url("test-key", http_method="PUT")

        mock_s3.generate_presigned_url.assert_called_once_with(
            ClientMethod="put_object",
            Params={"Bucket": "test-bucket", "Key": "test-key"},
            ExpiresIn=3600,
        )

    async def test_generate_presigned_url_exception(self, s3_settings: S3Settings) -> None:
        """Test generate_presigned_url raises S3ConnectionError on failure."""
        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(side_effect=Exception("URL generation failed"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)

        with (
            patch.object(_s3_backend(client)._session, "create_client", mock_create_client),
            pytest.raises(S3ConnectionError),
        ):
            await client.generate_presigned_url("test-key")

    @pytest.mark.parametrize(
        ("http_method", "constraints", "message"),
        [
            pytest.param(
                "GET",
                S3PresignedPutConstraints(content_type="application/pdf"),
                "only valid for presigned PUT",
                id="constraints-on-get",
            ),
            pytest.param(
                "PUT",
                S3PresignedPutConstraints(content_type="   "),
                "content_type must not be empty",
                id="blank-content-type",
            ),
            pytest.param(
                "PUT",
                S3PresignedPutConstraints(content_length=-1),
                "content_length must not be negative",
                id="negative-content-length",
            ),
        ],
    )
    async def test_presign_rejects_invalid_content_constraints_before_s3(
        self,
        s3_settings: S3Settings,
        http_method: str,
        constraints: S3PresignedPutConstraints,
        message: str,
    ) -> None:
        """Invalid signed-header combinations fail before credentials or S3 are used."""
        client = S3Client(s3_settings)

        with pytest.raises(ValueError, match=message):
            await client.generate_presigned_url(
                "test-key",
                http_method=http_method,
                put_constraints=constraints,
            )

    async def test_presigned_put_binds_all_declared_constraints(self, s3_settings: S3Settings) -> None:
        """Every declared upload constraint becomes part of the signed S3 request."""
        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(return_value="https://s3.example.com/presigned")

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        client = S3Client(s3_settings)
        constraints = S3PresignedPutConstraints(
            content_type="application/pdf",
            content_length=4096,
            checksum_sha256="base64-checksum",
        )

        with patch.object(_s3_backend(client)._session, "create_client", mock_create_client):
            await client.generate_presigned_url(
                "test-key",
                http_method="PUT",
                put_constraints=constraints,
            )

        assert mock_s3.generate_presigned_url.call_args.kwargs["Params"] == {
            "Bucket": "test-bucket",
            "Key": "test-key",
            "ContentType": "application/pdf",
            "ContentLength": 4096,
            "ChecksumSHA256": "base64-checksum",
        }


@pytest.fixture
def s3_settings_with_public_url() -> S3Settings:
    """S3Settings with both internal endpoint and public_url configured."""
    return S3Settings(
        endpoint="http://nohiki-infra-minio:9000",
        public_url="http://localhost:9002",
        access_key=SecretStr("test-access-key"),
        secret_key=SecretStr("test-secret-key"),
        bucket="test-bucket",
        region="us-east-1",
        connect_timeout=10,
        read_timeout=30,
    )


class TestS3ClientPresignedUrlWithPublicUrl:
    """Tests for generate_presigned_url endpoint override via public_url."""

    async def test_presigned_url_uses_public_url_as_endpoint(self, s3_settings_with_public_url: S3Settings) -> None:
        """generate_presigned_url creates client with public_url, not internal endpoint."""
        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(
            return_value="http://localhost:9002/test-bucket/test-key?X-Amz-Signature=abc"
        )
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings_with_public_url)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            result = await client.generate_presigned_url("test-key", http_method="PUT")

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://localhost:9002"
        assert "localhost:9002" in result

    async def test_get_object_still_uses_internal_endpoint(self, s3_settings_with_public_url: S3Settings) -> None:
        """get_object uses internal endpoint even when public_url is set."""

        class MockBody:
            chunks = iter([b"content", b""])

            async def read(self, amt: int) -> bytes:
                await asyncio.sleep(0)
                chunk = next(self.chunks)
                assert len(chunk) <= amt
                return chunk

            async def __aenter__(self) -> MockBody:
                return self

            async def __aexit__(self, *args: object) -> None:
                await asyncio.sleep(0)

        mock_s3 = AsyncMock()
        mock_s3.get_object = AsyncMock(return_value={"Body": MockBody()})
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings_with_public_url)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            await client.get_object("test-key")

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://nohiki-infra-minio:9000"

    async def test_presigned_url_without_public_url_uses_endpoint(self, s3_settings: S3Settings) -> None:
        """generate_presigned_url uses settings.endpoint when public_url is empty."""
        mock_s3 = AsyncMock()
        mock_s3.generate_presigned_url = AsyncMock(return_value="http://localhost:9000/presigned")
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            await client.generate_presigned_url("test-key", http_method="PUT")

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://localhost:9000"


class TestS3ClientGetClientEndpointOverride:
    """Tests for _get_client endpoint_override parameter."""

    async def test_endpoint_override_replaces_settings_endpoint(self, s3_settings: S3Settings) -> None:
        """_get_client uses endpoint_override when provided."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            async with _s3_backend(client)._get_client(endpoint_override="http://override:1234") as _:
                pass

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://override:1234"

    async def test_no_override_uses_settings_endpoint(self, s3_settings: S3Settings) -> None:
        """_get_client uses settings.endpoint when no override provided."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            async with _s3_backend(client)._get_client() as _:
                pass

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://localhost:9000"


class TestS3ClientCredentials:
    """Tests for S3Client credential handling."""

    async def test_client_uses_credentials_when_provided(self, s3_settings: S3Settings) -> None:
        """Test that client uses credentials when provided."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            await client.check_bucket_access()

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["aws_access_key_id"] == "test-access-key"
        assert call_kwargs["aws_secret_access_key"] == "test-secret-key"
        assert call_kwargs["endpoint_url"] == "http://localhost:9000"

    async def test_client_omits_credentials_when_not_provided(self, s3_settings_no_credentials: S3Settings) -> None:
        """Test that client omits credentials for IAM role mode."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()
        mock_create = MagicMock()

        @asynccontextmanager
        async def create_client_cm(*args: object, **kwargs: object) -> AsyncIterator[AsyncMock]:
            mock_create(*args, **kwargs)
            yield mock_s3

        client = S3Client(s3_settings_no_credentials)

        with patch.object(_s3_backend(client)._session, "create_client", create_client_cm):
            await client.check_bucket_access()

        call_kwargs = mock_create.call_args[1]
        assert "aws_access_key_id" not in call_kwargs
        assert "aws_secret_access_key" not in call_kwargs
        assert "endpoint_url" not in call_kwargs

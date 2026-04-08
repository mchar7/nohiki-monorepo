"""Tests for S3 health probe."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from nohiki_s3_client import S3Settings
from nohiki_s3_client.client import S3Client
from nohiki_s3_client.exceptions import S3ConnectionError, S3PermissionError
from nohiki_s3_client.health import S3Capability, S3HealthProbe, ensure_s3_ready
from pydantic import SecretStr

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
def s3_client(s3_settings: S3Settings) -> S3Client:
    """Create S3Client for testing."""
    return S3Client(s3_settings)


class TestS3Capability:
    """Tests for S3Capability enum."""

    def test_bucket_access_value(self) -> None:
        """BUCKET_ACCESS has correct value."""
        assert S3Capability.BUCKET_ACCESS.value == "bucket_access"

    def test_read_value(self) -> None:
        """READ has correct value."""
        assert S3Capability.READ.value == "read"

    def test_write_value(self) -> None:
        """WRITE has correct value."""
        assert S3Capability.WRITE.value == "write"


class TestS3HealthProbeInit:
    """Tests for S3HealthProbe initialization."""

    def test_init_default_capabilities(self, s3_client: S3Client) -> None:
        """Default capabilities is BUCKET_ACCESS only."""
        probe = S3HealthProbe(s3_client)
        assert probe._capabilities == {S3Capability.BUCKET_ACCESS}

    def test_init_custom_capabilities(self, s3_client: S3Client) -> None:
        """Custom capabilities are stored."""
        capabilities = {S3Capability.READ, S3Capability.WRITE}
        probe = S3HealthProbe(s3_client, capabilities=capabilities)
        assert probe._capabilities == capabilities

    def test_init_custom_health_check_key(self, s3_client: S3Client) -> None:
        """Custom health check key is stored."""
        probe = S3HealthProbe(s3_client, health_check_key="custom_key")
        assert probe._health_check_key == "custom_key"

    def test_init_custom_timeout(self, s3_client: S3Client) -> None:
        """Custom timeout is stored."""
        timeout = 5.0
        probe = S3HealthProbe(s3_client, timeout_seconds=timeout)
        assert probe._timeout_seconds == pytest.approx(timeout)

    def test_name_property(self, s3_client: S3Client) -> None:
        """Name property returns 's3'."""
        probe = S3HealthProbe(s3_client)
        assert probe.name == "s3"


class TestS3HealthProbeCheckBucketAccess:
    """Tests for bucket access health check."""

    async def test_check_bucket_access_healthy(self, s3_client: S3Client) -> None:
        """Healthy bucket access check."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
            result = await probe.check()

        assert result.is_healthy()
        assert result.name == "s3"
        assert "S3 is healthy" in result.message
        assert result.details["capabilities"]["bucket_access"] is True

    async def test_check_bucket_access_permission_error(self, s3_client: S3Client) -> None:
        """Bucket access check with permission error."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=S3PermissionError("test-bucket"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
            result = await probe.check()

        assert not result.is_healthy()
        assert "connection failed" in result.message.lower()

    async def test_check_bucket_access_connection_error(self, s3_client: S3Client) -> None:
        """Bucket access check with connection error."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=S3ConnectionError("Connection failed"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
            result = await probe.check()

        assert not result.is_healthy()
        assert "Bucket connection failed" in result.message

    async def test_check_bucket_access_os_error(self, s3_client: S3Client) -> None:
        """Bucket access check with OS error."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=OSError("Network error"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
            result = await probe.check()

        assert not result.is_healthy()
        assert "connection failed" in result.message.lower()


class TestS3HealthProbeCheckRead:
    """Tests for read capability health check."""

    async def test_check_read_healthy(self, s3_client: S3Client) -> None:
        """Healthy read check."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(return_value={"Contents": []})

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.READ})
            result = await probe.check()

        assert result.is_healthy()
        assert result.details["capabilities"]["read"] is True

    async def test_check_read_permission_error(self, s3_client: S3Client) -> None:
        """Read check with permission error."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(side_effect=S3PermissionError("test-bucket"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.READ})
            result = await probe.check()

        assert not result.is_healthy()
        assert "connection failed" in result.message.lower()

    async def test_check_read_connection_error(self, s3_client: S3Client) -> None:
        """Read check with connection error."""
        mock_s3 = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(side_effect=S3ConnectionError("Connection failed"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.READ})
            result = await probe.check()

        assert not result.is_healthy()
        assert "Read connection failed" in result.message


class TestS3HealthProbeCheckWrite:
    """Tests for write capability health check."""

    async def test_check_write_healthy(self, s3_client: S3Client) -> None:
        """Healthy write check."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()
        mock_s3.delete_object = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.WRITE})
            result = await probe.check()

        assert result.is_healthy()
        assert result.details["capabilities"]["write"] is True
        mock_s3.put_object.assert_called_once()
        mock_s3.delete_object.assert_called_once()

    async def test_check_write_permission_error(self, s3_client: S3Client) -> None:
        """Write check with permission error."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=S3PermissionError("test-key"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, capabilities={S3Capability.WRITE})
            result = await probe.check()

        assert not result.is_healthy()
        assert "connection failed" in result.message.lower()


class TestS3HealthProbeMultipleCapabilities:
    """Tests for multiple capability checks."""

    async def test_all_capabilities_healthy(self, s3_client: S3Client) -> None:
        """All capabilities healthy."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(return_value={"Contents": []})
        mock_s3.put_object = AsyncMock()
        mock_s3.delete_object = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(
                s3_client,
                capabilities={S3Capability.BUCKET_ACCESS, S3Capability.READ, S3Capability.WRITE},
            )
            result = await probe.check()

        assert result.is_healthy()
        assert result.details["capabilities"]["bucket_access"] is True
        assert result.details["capabilities"]["read"] is True
        assert result.details["capabilities"]["write"] is True

    async def test_one_capability_fails(self, s3_client: S3Client) -> None:
        """One capability fails, overall unhealthy."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()
        mock_s3.list_objects_v2 = AsyncMock(side_effect=S3PermissionError("test-bucket"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(
                s3_client,
                capabilities={S3Capability.BUCKET_ACCESS, S3Capability.READ},
            )
            result = await probe.check()

        assert not result.is_healthy()
        assert result.details["capabilities"]["bucket_access"] is True
        assert result.details["capabilities"]["read"] is False


class TestS3HealthProbeTimeout:
    """Tests for health check timeout."""

    async def test_timeout_error(self, s3_client: S3Client) -> None:
        """Health check times out."""
        mock_s3 = AsyncMock()

        async def slow_head_bucket(*_args: object, **_kwargs: object) -> None:
            await asyncio.sleep(2.0)

        mock_s3.head_bucket = slow_head_bucket

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client, timeout_seconds=0.1)
            result = await probe.check()

        assert not result.is_healthy()
        assert "timeout" in result.message.lower()

    async def test_unexpected_exception(self, s3_client: S3Client) -> None:
        """Unexpected exception during health check."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            probe = S3HealthProbe(s3_client)
            result = await probe.check()

        assert not result.is_healthy()
        assert "connection failed" in result.message.lower()
        assert result.details["capabilities"]["bucket_access"] is False


class TestEnsureS3Ready:
    """Tests for ensure_s3_ready function."""

    async def test_s3_ready_immediately(self, s3_client: S3Client) -> None:
        """S3 is ready on first check."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock()

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            await ensure_s3_ready(s3_client, timeout_seconds=5.0)

        mock_s3.head_bucket.assert_called_once()

    async def test_s3_ready_after_retries(self, s3_client: S3Client) -> None:
        """S3 becomes ready after retries."""
        mock_s3 = AsyncMock()
        call_count = 0

        async def head_bucket_with_retries(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                error_msg = "Not ready yet"
                raise S3ConnectionError(error_msg)

        mock_s3.head_bucket = head_bucket_with_retries

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with patch.object(s3_client._session, "create_client", mock_create_client):
            await ensure_s3_ready(s3_client, timeout_seconds=10.0, retry_interval_seconds=0.1)

        assert call_count == 3

    async def test_s3_timeout(self, s3_client: S3Client) -> None:
        """S3 never becomes ready, raises RuntimeError."""
        mock_s3 = AsyncMock()
        mock_s3.head_bucket = AsyncMock(side_effect=S3ConnectionError("Never ready"))

        @asynccontextmanager
        async def mock_create_client(*_args: object, **_kwargs: object) -> AsyncIterator[AsyncMock]:
            yield mock_s3

        with (
            patch.object(s3_client._session, "create_client", mock_create_client),
            pytest.raises(RuntimeError, match="S3 unavailable after"),
        ):
            await ensure_s3_ready(s3_client, timeout_seconds=0.5, retry_interval_seconds=0.1)


class TestS3HealthProbeErrorPaths:
    """Tests for S3HealthProbe error handling branches."""

    @pytest.mark.asyncio
    async def test_check_returns_unhealthy_on_os_error(self, s3_client: S3Client) -> None:
        """check() returns unhealthy when OSError is raised."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
        with patch.object(S3HealthProbe, "_check_bucket_access", side_effect=OSError("Network down")):
            result = await probe.check()
        assert result.status.value == "unhealthy"
        assert "connection failed" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_returns_unhealthy_on_unexpected_error(self, s3_client: S3Client) -> None:
        """check() returns unhealthy on unexpected exceptions."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
        with patch.object(S3HealthProbe, "_check_bucket_access", side_effect=ValueError("Unexpected")):
            result = await probe.check()
        assert result.status.value == "unhealthy"
        assert "unexpected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_bucket_access_permission_error(self, s3_client: S3Client) -> None:
        """_check_bucket_access returns failure on S3PermissionError."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
        with patch.object(s3_client, "check_bucket_access", side_effect=S3PermissionError("Denied")):
            ok, msg = await probe._check_bucket_access()
        assert ok is False
        assert msg is not None
        assert "permission denied" in msg.lower()

    @pytest.mark.asyncio
    async def test_check_bucket_access_os_error(self, s3_client: S3Client) -> None:
        """_check_bucket_access returns failure on OSError."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
        with patch.object(s3_client, "check_bucket_access", side_effect=OSError("DNS failure")):
            ok, msg = await probe._check_bucket_access()
        assert ok is False
        assert msg is not None
        assert "access failed" in msg.lower()

    @pytest.mark.asyncio
    async def test_check_read_os_error(self, s3_client: S3Client) -> None:
        """_check_read returns failure on OSError."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.READ})
        with patch.object(s3_client, "list_objects_sample", side_effect=OSError("Timeout")):
            ok, msg = await probe._check_read()
        assert ok is False
        assert msg is not None
        assert "access failed" in msg.lower()

    @pytest.mark.asyncio
    async def test_check_read_permission_error(self, s3_client: S3Client) -> None:
        """_check_read returns failure on S3PermissionError."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.READ})
        with patch.object(s3_client, "list_objects_sample", side_effect=S3PermissionError("Denied")):
            ok, msg = await probe._check_read()
        assert ok is False
        assert msg is not None
        assert "permission denied" in msg.lower()

    @pytest.mark.asyncio
    async def test_check_write_os_error(self, s3_client: S3Client) -> None:
        """_check_write returns failure on OSError."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.WRITE})
        with patch.object(s3_client, "put_object", side_effect=OSError("Write failed")):
            ok, msg = await probe._check_write()
        assert ok is False
        assert msg is not None
        assert "access failed" in msg.lower()

    @pytest.mark.asyncio
    async def test_check_write_permission_error(self, s3_client: S3Client) -> None:
        """_check_write returns failure on S3PermissionError."""
        probe = S3HealthProbe(s3_client, capabilities={S3Capability.WRITE})
        with patch.object(s3_client, "put_object", side_effect=S3PermissionError("Denied")):
            ok, msg = await probe._check_write()
        assert ok is False
        assert msg is not None
        assert "permission denied" in msg.lower()

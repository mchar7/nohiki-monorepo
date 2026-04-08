"""Tests for cache health check utilities."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_redis_utils import CacheHealthResult, HealthStatus, check_cache_health
from nohiki_redis_utils.health import (
    RedisHealthProbe,
    ensure_redis_ready,
)
from redis.asyncio import Redis, RedisError


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_status_values(self) -> None:
        """Verify health status enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"


class TestCacheHealthResult:
    """Tests for CacheHealthResult dataclass."""

    def test_health_result_creation(self) -> None:
        """Verify health result can be created with all fields."""
        result = CacheHealthResult(
            status=HealthStatus.HEALTHY,
            latency_ms=5.0,
            message="Cache is healthy",
            details={"key": "value"},
        )
        assert result.status == HealthStatus.HEALTHY
        assert result.latency_ms == pytest.approx(5.0)
        assert result.message == "Cache is healthy"
        assert result.details == {"key": "value"}

    def test_health_result_optional_details(self) -> None:
        """Verify details field is optional."""
        result = CacheHealthResult(
            status=HealthStatus.HEALTHY,
            latency_ms=5.0,
            message="Cache is healthy",
        )
        assert result.details is None


class TestCheckCacheHealth:
    """Tests for check_cache_health function."""

    @pytest.mark.asyncio
    async def test_healthy_with_fast_cache(self) -> None:
        """Health check returns HEALTHY with fast cache operations."""
        mock_cache = MagicMock()
        mock_cache._test_value = "health_check_test"

        async def mock_get(_key: str) -> str:
            lock = asyncio.Lock()
            async with lock:
                return str(mock_cache._test_value)

        async def mock_set(_key: str, value: str, ttl: int | None = None) -> None:
            del ttl
            lock = asyncio.Lock()
            async with lock:
                mock_cache._test_value = value

        async def mock_delete(_key: str) -> None:
            """Mock delete operation."""
            lock = asyncio.Lock()
            async with lock:
                # No-op for testing
                pass

        mock_cache.set = mock_set
        mock_cache.get = mock_get
        mock_cache.delete = mock_delete

        result = await check_cache_health(mock_cache)

        assert result.status == HealthStatus.HEALTHY
        assert result.message == "Cache is healthy"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_degraded_with_slow_cache(self) -> None:
        """Health check returns DEGRADED when latency exceeds threshold."""
        mock_cache = MagicMock()

        async def slow_set(_key: str, value: str, ttl: int | None = None) -> None:
            del ttl
            await asyncio.sleep(0.15)
            mock_cache._test_value = value

        async def slow_get(_key: str) -> str:
            await asyncio.sleep(0)
            return str(mock_cache._test_value)

        mock_cache.set = slow_set
        mock_cache.get = slow_get
        mock_cache.delete = AsyncMock()

        result = await check_cache_health(
            mock_cache,
            timeout_ms=1000.0,
            degraded_threshold_ms=100.0,
        )

        assert result.status == HealthStatus.DEGRADED
        assert "exceeds degraded threshold" in result.message
        assert result.latency_ms >= 100

    @pytest.mark.asyncio
    async def test_unhealthy_on_timeout(self) -> None:
        """Health check returns UNHEALTHY when latency exceeds timeout."""
        mock_cache = MagicMock()

        async def very_slow_set(_key: str, value: str, ttl: int | None = None) -> None:
            del ttl
            await asyncio.sleep(0.2)
            mock_cache._test_value = value

        async def slow_get(_key: str) -> str:
            await asyncio.sleep(0)
            return str(mock_cache._test_value)

        mock_cache.set = very_slow_set
        mock_cache.get = slow_get
        mock_cache.delete = AsyncMock()

        result = await check_cache_health(
            mock_cache,
            timeout_ms=100.0,
            degraded_threshold_ms=50.0,
        )

        assert result.status == HealthStatus.UNHEALTHY
        assert "exceeds timeout" in result.message

    @pytest.mark.asyncio
    async def test_unhealthy_on_exception(self) -> None:
        """Health check returns UNHEALTHY on cache exception."""
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock(side_effect=RedisError("Redis connection failed"))

        result = await check_cache_health(mock_cache)

        assert result.status == HealthStatus.UNHEALTHY
        assert "Health check failed" in result.message
        assert result.details is not None
        assert "error" in result.details
        assert "Redis connection failed" in str(result.details["error"])

    @pytest.mark.asyncio
    async def test_unhealthy_on_read_mismatch(self) -> None:
        """Health check returns UNHEALTHY when read value doesn't correlation written value."""
        mock_cache = MagicMock()
        mock_cache.set = AsyncMock()
        mock_cache.get = AsyncMock(return_value="wrong_value")
        mock_cache.delete = AsyncMock()

        result = await check_cache_health(mock_cache)

        assert result.status == HealthStatus.UNHEALTHY
        assert "does not correlation" in result.message
        assert result.details is not None
        assert result.details["actual"] == "wrong_value"


class TestRedisHealthProbe:
    """Tests for RedisHealthProbe class."""

    def test_initialization_defaults(self) -> None:
        """Probe initializes with default values."""
        probe = RedisHealthProbe("redis://localhost:6379")

        assert probe.name == "redis"
        assert probe._redis_url == "redis://localhost:6379"
        assert probe._timeout_ms == pytest.approx(1000.0)
        assert probe._degraded_threshold_ms == pytest.approx(100.0)
        assert probe._require_write is True

    def test_initialization_custom(self) -> None:
        """Probe initializes with custom values."""
        probe = RedisHealthProbe(
            "redis://localhost:6379",
            timeout_ms=2000.0,
            degraded_threshold_ms=200.0,
            require_write=False,
        )

        assert probe._timeout_ms == pytest.approx(2000.0)
        assert probe._degraded_threshold_ms == pytest.approx(200.0)
        assert probe._require_write is False

    @pytest.mark.asyncio
    async def test_check_ping_only_healthy(self) -> None:
        """PING-only check returns healthy when Redis responds."""
        probe = RedisHealthProbe("redis://localhost:6379", require_write=False)

        mock_client = MagicMock(spec=Redis)
        mock_client.ping = AsyncMock(return_value=True)

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.is_healthy() is True
            assert result.name == "redis"

    @pytest.mark.asyncio
    async def test_check_ping_fails(self) -> None:
        """PING check returns unhealthy when Redis doesn't respond."""
        probe = RedisHealthProbe("redis://localhost:6379", require_write=False)

        mock_client = MagicMock(spec=Redis)
        mock_client.ping = AsyncMock(return_value=False)

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "returned False" in result.message

    @pytest.mark.asyncio
    async def test_check_read_write_healthy(self) -> None:
        """Read-write check returns healthy when operations succeed."""
        probe = RedisHealthProbe("redis://localhost:6379", require_write=True)

        stored_value: bytes | None = None

        mock_client = MagicMock(spec=Redis)

        def do_get(_key: str) -> bytes | None:
            return stored_value

        def do_set(_key: str, value: bytes, **_kwargs: object) -> None:
            nonlocal stored_value
            stored_value = value

        mock_client.get = AsyncMock(side_effect=do_get)
        mock_client.set = AsyncMock(side_effect=do_set)
        mock_client.delete = AsyncMock()

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.is_healthy() is True
            assert result.name == "redis"

    @pytest.mark.asyncio
    async def test_check_read_write_mismatch(self) -> None:
        """Read-write check fails when values don't match."""
        probe = RedisHealthProbe("redis://localhost:6379", require_write=True)

        mock_client = MagicMock(spec=Redis)
        mock_client.set = AsyncMock()
        mock_client.get = AsyncMock(return_value=b"different_value")
        mock_client.delete = AsyncMock()

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "mismatch" in result.message

    @pytest.mark.asyncio
    async def test_check_read_write_none(self) -> None:
        """Read-write check fails when read returns None."""
        probe = RedisHealthProbe("redis://localhost:6379", require_write=True)

        mock_client = MagicMock(spec=Redis)
        mock_client.set = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.delete = AsyncMock()

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "returned None" in result.message

    @pytest.mark.asyncio
    async def test_check_connection_error(self) -> None:
        """Check returns unhealthy on connection error."""
        probe = RedisHealthProbe("redis://localhost:6379", require_write=False)

        mock_client = MagicMock(spec=Redis)
        mock_client.ping = AsyncMock(side_effect=RedisError("Connection refused"))

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "Connection refused" in result.message

    @pytest.mark.asyncio
    async def test_check_degraded_latency(self) -> None:
        """Check returns degraded when latency is high."""
        probe = RedisHealthProbe(
            "redis://localhost:6379",
            require_write=False,
            degraded_threshold_ms=1.0,
        )

        mock_client = MagicMock(spec=Redis)

        async def slow_ping() -> bool:
            await asyncio.sleep(0.05)  # 50ms
            return True

        mock_client.ping = slow_ping

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.status.value == "degraded"

    @pytest.mark.asyncio
    async def test_check_unhealthy_timeout(self) -> None:
        """Check returns unhealthy when latency exceeds timeout."""
        probe = RedisHealthProbe(
            "redis://localhost:6379",
            require_write=False,
            timeout_ms=10.0,
        )

        mock_client = MagicMock(spec=Redis)

        async def slow_ping() -> bool:
            await asyncio.sleep(0.1)  # 100ms
            return True

        mock_client.ping = slow_ping

        with patch(
            "nohiki_redis_utils.health.redis_async.from_url",
            return_value=mock_client,
        ):
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "exceeds timeout" in result.message

    @pytest.mark.asyncio
    async def test_close_client(self) -> None:
        """Close properly closes Redis client."""
        probe = RedisHealthProbe("redis://localhost:6379")

        mock_client = MagicMock(spec=Redis)
        mock_client.aclose = AsyncMock()
        probe._client = mock_client

        await probe.close()

        mock_client.aclose.assert_called_once()
        assert probe._client is None

    @pytest.mark.asyncio
    async def test_close_no_client(self) -> None:
        """Close does nothing when no client exists."""
        probe = RedisHealthProbe("redis://localhost:6379")

        # Should not raise
        await probe.close()


class TestEnsureRedisReady:
    """Tests for ensure_redis_ready function."""

    @pytest.mark.asyncio
    async def test_redis_ready_immediately(self) -> None:
        """Returns immediately when Redis is available."""
        with patch("nohiki_redis_utils.health.RedisHealthProbe") as mock_probe_class:
            mock_probe = MagicMock()
            mock_probe.check = AsyncMock()
            mock_probe.close = AsyncMock()

            # Return healthy result
            mock_result = MagicMock()
            mock_result.is_healthy = MagicMock(return_value=True)
            mock_probe.check = AsyncMock(return_value=mock_result)

            mock_probe_class.return_value = mock_probe

            await ensure_redis_ready("redis://localhost:6379")

            mock_probe.check.assert_called()
            mock_probe.close.assert_called()

    @pytest.mark.asyncio
    async def test_redis_becomes_ready(self) -> None:
        """Waits and returns when Redis becomes available."""
        with patch("nohiki_redis_utils.health.RedisHealthProbe") as mock_probe_class:
            mock_probe = MagicMock()

            # First unhealthy, then healthy
            mock_unhealthy = MagicMock()
            mock_unhealthy.is_healthy = MagicMock(return_value=False)

            mock_healthy = MagicMock()
            mock_healthy.is_healthy = MagicMock(return_value=True)

            mock_probe.check = AsyncMock(side_effect=[mock_unhealthy, mock_healthy])
            mock_probe.close = AsyncMock()

            mock_probe_class.return_value = mock_probe

            await ensure_redis_ready(
                "redis://localhost:6379",
                timeout_seconds=1.0,
                retry_interval_seconds=0.1,
            )

            assert mock_probe.check.call_count == 2

    @pytest.mark.asyncio
    async def test_redis_timeout(self) -> None:
        """Raises RuntimeError when Redis never becomes available."""
        mock_probe = MagicMock()

        mock_unhealthy = MagicMock()
        mock_unhealthy.is_healthy = MagicMock(return_value=False)
        mock_unhealthy.message = "Connection refused"

        mock_probe.check = AsyncMock(return_value=mock_unhealthy)
        mock_probe.close = AsyncMock()

        with (
            patch("nohiki_redis_utils.health.RedisHealthProbe", return_value=mock_probe),
            pytest.raises(RuntimeError, match="unavailable after"),
        ):
            await ensure_redis_ready(
                "redis://localhost:6379",
                timeout_seconds=0.3,
                retry_interval_seconds=0.1,
            )

    @pytest.mark.asyncio
    async def test_redis_always_closed(self) -> None:
        """Probe is always closed even on success."""
        with patch("nohiki_redis_utils.health.RedisHealthProbe") as mock_probe_class:
            mock_probe = MagicMock()

            mock_result = MagicMock()
            mock_result.is_healthy = MagicMock(return_value=True)

            mock_probe.check = AsyncMock(return_value=mock_result)
            mock_probe.close = AsyncMock()

            mock_probe_class.return_value = mock_probe

            await ensure_redis_ready("redis://localhost:6379")

            mock_probe.close.assert_called_once()

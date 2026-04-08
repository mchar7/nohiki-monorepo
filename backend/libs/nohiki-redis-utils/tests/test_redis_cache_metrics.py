"""Tests for RedisCache metrics recording.

This module covers the exception handlers that record metrics when RedisError
is raised.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from nohiki_redis_utils.redis_cache import RedisCache
from redis.asyncio import RedisError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def cache() -> AsyncGenerator[RedisCache]:
    """Create a RedisCache and close it after the test to prevent resource leaks."""
    instance = RedisCache(redis_url="redis://localhost:6379", service_name="test")
    yield instance
    await instance.close()


class TestRedisCacheMetricsErrorRecording:
    """Tests for metrics recording when circuit breaker raises RedisError."""

    @pytest.mark.asyncio
    async def test_get_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """get() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.get("key")

        assert result is None
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """set() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            await cache.set("key", "value")

        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """delete() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            await cache.delete("key")

        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_exists_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """exists() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.exists("key")

        assert result is False
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_setnx_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """setnx() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.setnx("key", "value")

        assert result is False
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_sadd_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """sadd() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.sadd("key", "member")

        assert result == 0
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_srem_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """srem() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.srem("key", "member")

        assert result == 0
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_smembers_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """smembers() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.smembers("key")

        assert result == set()
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_sismember_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """sismember() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.sismember("key", "member")

        assert result is False
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_zadd_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """zadd() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.zadd("key", "member", 1.0)

        assert result == 0
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_zrem_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """zrem() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.zrem("key", "member")

        assert result == 0
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_zrange_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """zrange() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.zrange("key", 0, -1)

        assert result == []
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_zrangebyscore_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """zrangebyscore() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.zrangebyscore("key", 0.0, 100.0)

        assert result == []
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_zcard_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """zcard() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.zcard("key")

        assert result == 0
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_eval_script_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """eval_script() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.eval_script("return 1", ["key"], [])

        assert result == []
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_incr_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """incr() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.incr("key")

        assert result == 0
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_expire_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """expire() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.expire("key", 60)

        assert result is False
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_ttl_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """ttl() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.ttl("key")

        assert result == -2
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_bytes_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """get_bytes() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            result = await cache.get_bytes("key")

        assert result is None
        mock_metrics.record_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_bytes_records_error_on_redis_error(self, cache: RedisCache) -> None:
        """set_bytes() records error metric when circuit breaker raises RedisError."""
        mock_metrics = MagicMock()
        cache._metrics = mock_metrics

        with patch.object(cache._circuit_breaker, "call", side_effect=RedisError("Connection failed")):
            await cache.set_bytes("key", b"value")

"""Additional tests for RedisCache error handling and edge cases.

This module covers exception handling paths to improve coverage of redis_cache.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_redis_utils.distributed_lock import DistributedLockError
from nohiki_redis_utils.redis_cache import RedisCache
from redis.asyncio import Redis, RedisError


@pytest.fixture
def cache() -> RedisCache:
    """Create a RedisCache with mocked connections to avoid resource leaks."""
    mock_redis = MagicMock(spec=Redis)
    mock_redis_binary = MagicMock(spec=Redis)
    with patch(
        "nohiki_redis_utils.redis_cache.Redis.from_url",
        side_effect=[mock_redis, mock_redis_binary],
    ):
        return RedisCache(redis_url="redis://localhost:6379", service_name="test")


class TestRedisCacheErrorHandling:
    """Tests for error handling in RedisCache operations."""

    @pytest.mark.asyncio
    async def test_get_handles_redis_error(self, cache: RedisCache) -> None:
        """get() returns None on RedisError."""
        cache._redis.get = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.get("key")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_handles_redis_error(self, cache: RedisCache) -> None:
        """set() handles RedisError gracefully."""
        cache._redis.set = AsyncMock(side_effect=RedisError("Connection lost"))
        cache._redis.setex = AsyncMock(side_effect=RedisError("Connection lost"))

        # Should not raise
        await cache.set("key", "value")

    @pytest.mark.asyncio
    async def test_set_with_ttl_handles_redis_error(self, cache: RedisCache) -> None:
        """set() with TTL handles RedisError gracefully."""
        cache._redis.setex = AsyncMock(side_effect=RedisError("Connection lost"))

        # Should not raise
        await cache.set("key", "value", ttl=60)

    @pytest.mark.asyncio
    async def test_delete_handles_redis_error(self, cache: RedisCache) -> None:
        """delete() handles RedisError gracefully."""
        cache._redis.delete = AsyncMock(side_effect=RedisError("Connection lost"))

        # Should not raise
        await cache.delete("key")

    @pytest.mark.asyncio
    async def test_exists_handles_redis_error(self, cache: RedisCache) -> None:
        """exists() returns False on RedisError."""
        cache._redis.exists = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.exists("key")

        assert result is False

    @pytest.mark.asyncio
    async def test_setnx_handles_redis_error(self, cache: RedisCache) -> None:
        """setnx() returns False on RedisError."""
        cache._redis.set = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.setnx("key", "value")

        assert result is False

    @pytest.mark.asyncio
    async def test_sadd_handles_redis_error(self, cache: RedisCache) -> None:
        """sadd() returns 0 on RedisError."""
        cache._redis.sadd = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.sadd("key", "member")

        assert result == 0

    @pytest.mark.asyncio
    async def test_srem_handles_redis_error(self, cache: RedisCache) -> None:
        """srem() returns 0 on RedisError."""
        cache._redis.srem = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.srem("key", "member")

        assert result == 0

    @pytest.mark.asyncio
    async def test_smembers_handles_redis_error(self, cache: RedisCache) -> None:
        """smembers() returns empty set on RedisError."""
        cache._redis.smembers = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.smembers("key")

        assert result == set()

    @pytest.mark.asyncio
    async def test_sismember_handles_redis_error(self, cache: RedisCache) -> None:
        """sismember() returns False on RedisError."""
        cache._redis.sismember = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.sismember("key", "member")

        assert result is False

    @pytest.mark.asyncio
    async def test_zadd_handles_redis_error(self, cache: RedisCache) -> None:
        """zadd() returns 0 on RedisError."""
        cache._redis.zadd = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.zadd("key", "member", 1.0)

        assert result == 0

    @pytest.mark.asyncio
    async def test_zrem_handles_redis_error(self, cache: RedisCache) -> None:
        """zrem() returns 0 on RedisError."""
        cache._redis.zrem = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.zrem("key", "member")

        assert result == 0

    @pytest.mark.asyncio
    async def test_zrange_handles_redis_error(self, cache: RedisCache) -> None:
        """zrange() returns empty list on RedisError."""
        cache._redis.zrange = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.zrange("key", 0, -1)

        assert result == []

    @pytest.mark.asyncio
    async def test_zrangebyscore_handles_redis_error(self, cache: RedisCache) -> None:
        """zrangebyscore() returns empty list on RedisError."""
        cache._redis.zrangebyscore = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.zrangebyscore("key", 0.0, 100.0)

        assert result == []

    @pytest.mark.asyncio
    async def test_zcard_handles_redis_error(self, cache: RedisCache) -> None:
        """zcard() returns 0 on RedisError."""
        cache._redis.zcard = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.zcard("key")

        assert result == 0

    @pytest.mark.asyncio
    async def test_eval_script_handles_redis_error(self, cache: RedisCache) -> None:
        """eval_script() returns empty list on RedisError."""
        cache._redis.execute_command = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.eval_script("return 1", ["key"], ["arg"])

        assert result == []

    @pytest.mark.asyncio
    async def test_get_bytes_handles_redis_error(self, cache: RedisCache) -> None:
        """get_bytes() returns None on RedisError."""
        cache._redis_binary.get = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.get_bytes("key")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_bytes_handles_redis_error(self, cache: RedisCache) -> None:
        """set_bytes() handles RedisError gracefully."""
        cache._redis_binary.set = AsyncMock(side_effect=RedisError("Connection lost"))
        cache._redis_binary.setex = AsyncMock(side_effect=RedisError("Connection lost"))

        # Should not raise
        await cache.set_bytes("key", b"value")

    @pytest.mark.asyncio
    async def test_incr_handles_redis_error(self, cache: RedisCache) -> None:
        """incr() returns 0 on RedisError."""
        cache._redis.incr = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.incr("key")

        assert result == 0

    @pytest.mark.asyncio
    async def test_expire_handles_redis_error(self, cache: RedisCache) -> None:
        """expire() returns False on RedisError."""
        cache._redis.expire = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.expire("key", 60)

        assert result is False

    @pytest.mark.asyncio
    async def test_ttl_handles_redis_error(self, cache: RedisCache) -> None:
        """ttl() returns -2 on RedisError."""
        cache._redis.ttl = AsyncMock(side_effect=RedisError("Connection lost"))

        result = await cache.ttl("key")

        assert result == -2

    @pytest.mark.asyncio
    async def test_setnx_strict_propagates_redis_error(self, cache: RedisCache) -> None:
        """setnx_strict() must not turn backend failure into an existing-key result."""
        cache._redis.setnx = AsyncMock(side_effect=RedisError("Connection lost"))

        with pytest.raises(RedisError, match="Connection lost"):
            await cache.setnx_strict("key", "value")

    @pytest.mark.asyncio
    async def test_incr_with_ttl_strict_propagates_redis_error(self, cache: RedisCache) -> None:
        """incr_with_ttl_strict() must surface backend failure instead of returning zero."""
        cache._redis.execute_command = AsyncMock(side_effect=RedisError("Connection lost"))

        with pytest.raises(RedisError, match="Connection lost"):
            await cache.incr_with_ttl_strict("key", expiry=60)


class TestRedisCacheCircuitBreakerAccess:
    """Tests for circuit breaker property."""

    def test_circuit_breaker_property(self, cache: RedisCache) -> None:
        """circuit_breaker property returns the circuit breaker instance."""
        cb = cache.circuit_breaker

        assert cb is cache._circuit_breaker


class TestRedisCacheJsonHandling:
    """Tests for JSON serialization edge cases."""

    @pytest.mark.asyncio
    async def test_get_returns_string_for_non_json(self, cache: RedisCache) -> None:
        """get() returns raw string for non-JSON data."""
        cache._redis.get = AsyncMock(return_value="plain string value")

        result = await cache.get("key")

        assert result == "plain string value"

    @pytest.mark.asyncio
    async def test_get_returns_dict_for_json_object(self, cache: RedisCache) -> None:
        """get() returns dict for JSON object."""
        cache._redis.get = AsyncMock(return_value='{"key": "value"}')

        result = await cache.get("key")

        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_returns_list_for_json_array(self, cache: RedisCache) -> None:
        """get() returns list for JSON array."""
        cache._redis.get = AsyncMock(return_value="[1, 2, 3]")

        result = await cache.get("key")

        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_get_internal_handles_none(self, cache: RedisCache) -> None:
        """_get_internal returns None when key doesn't exist."""
        cache._redis.get = AsyncMock(return_value=None)

        result = await cache._get_internal("key")

        assert result is None


class TestRedisCacheSetOperations:
    """Tests for set operations with empty results."""

    @pytest.mark.asyncio
    async def test_sadd_multiple_members(self, cache: RedisCache) -> None:
        """sadd() handles multiple members."""
        cache._redis.sadd = AsyncMock(return_value=3)

        result = await cache.sadd("key", "a", "b", "c")

        assert result == 3

    @pytest.mark.asyncio
    async def test_srem_multiple_members(self, cache: RedisCache) -> None:
        """srem() handles multiple members."""
        cache._redis.srem = AsyncMock(return_value=2)

        result = await cache.srem("key", "a", "b")

        assert result == 2

    @pytest.mark.asyncio
    async def test_smembers_returns_set(self, cache: RedisCache) -> None:
        """smembers() converts result to set."""
        cache._redis.smembers = AsyncMock(return_value=["a", "b", "c"])

        result = await cache.smembers("key")

        assert result == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_smembers_empty_result(self, cache: RedisCache) -> None:
        """smembers() returns empty set for empty result."""
        cache._redis.smembers = AsyncMock(return_value=[])

        result = await cache.smembers("key")

        assert result == set()


class TestRedisCacheZSetOperations:
    """Tests for sorted set operations with edge cases."""

    @pytest.mark.asyncio
    async def test_zrangebyscore_with_count(self, cache: RedisCache) -> None:
        """zrangebyscore() handles count parameter."""
        cache._redis.zrangebyscore = AsyncMock(return_value=["a", "b"])

        result = await cache.zrangebyscore("key", 0.0, 100.0, offset=0, count=10)

        assert result == ["a", "b"]

    @pytest.mark.asyncio
    async def test_zrangebyscore_without_count(self, cache: RedisCache) -> None:
        """zrangebyscore() handles no count parameter."""
        cache._redis.zrangebyscore = AsyncMock(return_value=["a", "b", "c"])

        result = await cache.zrangebyscore("key", 0.0, 100.0)

        assert result == ["a", "b", "c"]


class TestRedisCacheEvalScript:
    """Tests for Lua script execution."""

    @pytest.mark.asyncio
    async def test_eval_script_with_bytes_result(self, cache: RedisCache) -> None:
        """eval_script() decodes bytes in result."""
        cache._redis.execute_command = AsyncMock(return_value=[b"hello", b"world"])

        result = await cache.eval_script("return {KEYS[1]}", ["key"], [])

        assert result == ["hello", "world"]

    @pytest.mark.asyncio
    async def test_eval_script_with_string_result(self, cache: RedisCache) -> None:
        """eval_script() handles string results."""
        cache._redis.execute_command = AsyncMock(return_value=["hello", "world"])

        result = await cache.eval_script("return {KEYS[1]}", ["key"], [])

        assert result == ["hello", "world"]

    @pytest.mark.asyncio
    async def test_eval_script_with_non_list_result(self, cache: RedisCache) -> None:
        """eval_script() returns empty list for non-list result."""
        cache._redis.execute_command = AsyncMock(return_value="not a list")

        result = await cache.eval_script("return 1", ["key"], [])

        assert result == []


class TestRedisCacheLockTimeout:
    """Tests for lock acquisition timeout."""

    @pytest.mark.asyncio
    async def test_acquire_lock_timeout(self, cache: RedisCache) -> None:
        """acquire_lock() returns False on timeout."""
        cache._redis.set = AsyncMock(return_value=False)

        result = await cache.acquire_lock("lock_key", "value", ttl_seconds=60, timeout_seconds=0.1)

        assert result is False


class TestRedisCacheDistributedLockError:
    """Tests for distributed lock context manager error handling."""

    @pytest.mark.asyncio
    async def test_distributed_lock_timeout_raises(self, cache: RedisCache) -> None:
        """distributed_lock() raises DistributedLockError on timeout."""
        with (
            patch.object(cache, "acquire_lock", return_value=False),
            pytest.raises(DistributedLockError, match="test_op"),
        ):
            async with cache.distributed_lock("test_op", timeout_seconds=0.01):
                pass

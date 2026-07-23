"""Tests for Redis cache implementation with binary data support."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from nohiki_redis_utils.redis_cache import RedisCache
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.fixture
def _redis_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace Redis construction with a deterministic failing client."""
    monkeypatch.setattr("socket.getaddrinfo", Mock(side_effect=AssertionError("Unexpected DNS lookup")))
    client = AsyncMock(spec=Redis)
    error = RedisConnectionError("Redis unavailable")
    for operation in (
        "execute_command",
        "expire",
        "get",
        "sadd",
        "set",
        "setnx",
        "sismember",
        "smembers",
        "srem",
        "ttl",
        "zadd",
        "zcard",
        "zrange",
        "zrangebyscore",
        "zrem",
    ):
        getattr(client, operation).side_effect = error
    monkeypatch.setattr(Redis, "from_url", Mock(return_value=client))


class TestRedisCacheBinaryOperations:
    """Tests for binary data operations (get_bytes/set_bytes)."""

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_set_and_get_bytes(self, redis_container: str) -> None:
        """Verify basic set_bytes and get_bytes operations."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            test_data = b"binary data \x00\x01\x02\xff"
            await cache.set_bytes("test_key", test_data)
            result = await cache.get_bytes("test_key")
            assert result == test_data
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_get_bytes_nonexistent_returns_none(self, redis_container: str) -> None:
        """Verify get_bytes returns None for nonexistent key."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            result = await cache.get_bytes("nonexistent")
            assert result is None
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_set_bytes_with_ttl(self, redis_container: str) -> None:
        """Verify set_bytes respects TTL."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            test_data = b"expiring data"
            await cache.set_bytes("ttl_key", test_data, ttl=timedelta(milliseconds=50))
            result = await cache.get_bytes("ttl_key")
            assert result == test_data

            async with asyncio.timeout(0.5):
                while await cache.get_bytes("ttl_key") is not None:  # noqa: ASYNC110 -- Redis TTL expiry has no event.
                    await asyncio.sleep(0.005)

            result_after_ttl = await cache.get_bytes("ttl_key")
            assert result_after_ttl is None
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_set_bytes_overwrites_existing(self, redis_container: str) -> None:
        """Verify set_bytes overwrites existing value."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.set_bytes("key", b"data1")
            await cache.set_bytes("key", b"data2")
            result = await cache.get_bytes("key")
            assert result == b"data2"
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_binary_data_preserves_null_bytes(self, redis_container: str) -> None:
        """Verify binary data with null bytes is preserved correctly."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            test_data = b"\x00\x00\xff\xff\x00\x00"
            await cache.set_bytes("null_bytes", test_data)
            result = await cache.get_bytes("null_bytes")
            assert result == test_data
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_large_binary_data(self, redis_container: str) -> None:
        """Verify large binary data can be stored and retrieved."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            # 1MB of binary data
            test_data = bytes(range(256)) * 4096
            await cache.set_bytes("large_data", test_data)
            result = await cache.get_bytes("large_data")
            assert result == test_data
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_service_name_isolation_for_binary(self, redis_container: str) -> None:
        """Verify service name provides key isolation for binary data."""
        cache1 = RedisCache(redis_url=redis_container, service_name="service1")
        cache2 = RedisCache(redis_url=redis_container, service_name="service2")
        try:
            await cache1.set_bytes("shared_key", b"service1_data")
            await cache2.set_bytes("shared_key", b"service2_data")

            result1 = await cache1.get_bytes("shared_key")
            result2 = await cache2.get_bytes("shared_key")

            assert result1 == b"service1_data"
            assert result2 == b"service2_data"
        finally:
            await cache1.close()
            await cache2.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_delete_binary_data(self, redis_container: str) -> None:
        """Verify delete works with binary data."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.set_bytes("delete_key", b"to_delete")
            await cache.delete("delete_key")
            result = await cache.get_bytes("delete_key")
            assert result is None
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_exists_with_binary_data(self, redis_container: str) -> None:
        """Verify exists works with binary data."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.set_bytes("exists_key", b"data")
            assert await cache.exists("exists_key") is True
            await cache.delete("exists_key")
            assert await cache.exists("exists_key") is False
        finally:
            await cache.close()


class TestRedisCacheCircuitBreakerWithBinary:
    """Tests for circuit breaker behavior with binary operations."""

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_circuit_breaker_fallback_on_error(self) -> None:
        """Verify circuit breaker provides fallback on connection error."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            # Should return None (fallback) instead of raising
            result = await cache.get_bytes("any_key")
            assert result is None
        finally:
            await cache.close()

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_set_bytes_handles_connection_error_gracefully(self) -> None:
        """Verify set_bytes handles connection errors gracefully."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            # Should not raise, circuit breaker handles it
            await cache.set_bytes("key", b"data")
        finally:
            await cache.close()


class TestRedisCacheIncrExpireTtl:
    """Tests for incr, expire, and ttl operations."""

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_incr_creates_key_with_one(self, redis_container: str) -> None:
        """Verify incr creates key with value 1 if doesn't exist."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            result = await cache.incr("new_counter")
            assert result == 1
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_incr_increments_existing_value(self, redis_container: str) -> None:
        """Verify incr increments existing integer value."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.incr("counter")
            await cache.incr("counter")
            result = await cache.incr("counter")
            assert result == 3
        finally:
            await cache.close()

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_incr_handles_connection_error(self) -> None:
        """Verify incr returns 0 on connection error."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            result = await cache.incr("any_key")
            assert result == 0
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_expire_sets_ttl_on_key(self, redis_container: str) -> None:
        """Verify expire sets TTL on existing key."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.set("expire_test", "value")
            result = await cache.expire("expire_test", 60)
            assert result is True

            ttl = await cache.ttl("expire_test")
            assert 0 < ttl <= 60
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_expire_returns_false_for_nonexistent_key(self, redis_container: str) -> None:
        """Verify expire returns False for nonexistent key."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            result = await cache.expire("nonexistent_key", 60)
            assert result is False
        finally:
            await cache.close()

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_expire_handles_connection_error(self) -> None:
        """Verify expire returns False on connection error."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            result = await cache.expire("any_key", 60)
            assert result is False
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_ttl_returns_remaining_time(self, redis_container: str) -> None:
        """Verify ttl returns remaining time for key with expiry."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.set("ttl_test", "value", ttl=120)
            result = await cache.ttl("ttl_test")
            assert 0 < result <= 120
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_ttl_returns_minus_two_for_nonexistent(self, redis_container: str) -> None:
        """Verify ttl returns -2 for nonexistent key."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            result = await cache.ttl("nonexistent_ttl")
            assert result == -2
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_ttl_returns_minus_one_for_no_expiry(self, redis_container: str) -> None:
        """Verify ttl returns -1 for key without expiry."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            await cache.set("no_expiry", "value")
            result = await cache.ttl("no_expiry")
            assert result == -1
        finally:
            await cache.close()

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_ttl_handles_connection_error(self) -> None:
        """Verify ttl returns -2 on connection error."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            result = await cache.ttl("any_key")
            assert result == -2
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_incr_and_expire_workflow(self, redis_container: str) -> None:
        """Verify incr and expire work together for rate limiting pattern."""
        cache = RedisCache(redis_url=redis_container, service_name="test")
        try:
            # Simulate rate limiting pattern
            key = "rate_limit:user:123"
            count = await cache.incr(key)
            assert count == 1

            # Set expiry on first increment
            await cache.expire(key, 60)

            # Subsequent increments
            count = await cache.incr(key)
            assert count == 2

            # Verify TTL is set
            ttl = await cache.ttl(key)
            assert 0 < ttl <= 60
        finally:
            await cache.close()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_incr_with_ttl_strict_sets_ttl_only_on_first_increment(self, redis_cache: RedisCache) -> None:
        """The fixed-window counter gets a TTL atomically and preserves an existing window."""
        key = "strict_fixed_window_atomic_ttl"
        await redis_cache.delete(key)

        first = await redis_cache.incr_with_ttl_strict(key, expiry=60)
        first_ttl = await redis_cache.ttl(key)
        assert first == 1
        assert 0 < first_ttl <= 60

        assert await redis_cache.expire(key, 120) is True
        second = await redis_cache.incr_with_ttl_strict(key, expiry=1)
        second_ttl = await redis_cache.ttl(key)

        assert second == 2
        assert 60 < second_ttl <= 120
        await redis_cache.delete(key)


class TestRedisCacheSetnx:
    """Tests for setnx operation."""

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_setnx_sets_new_key(self, redis_cache: RedisCache) -> None:
        """Verify setnx sets value for new key."""
        result = await redis_cache.setnx("new_setnx_key", "value")
        assert result is True
        val = await redis_cache.get("new_setnx_key")
        assert val == "value"

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_setnx_does_not_overwrite(self, redis_cache: RedisCache) -> None:
        """Verify setnx does not overwrite existing key."""
        await redis_cache.set("existing_key", "original")
        result = await redis_cache.setnx("existing_key", "new")
        assert result is False
        val = await redis_cache.get("existing_key")
        assert val == "original"

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_setnx_with_ttl(self, redis_cache: RedisCache) -> None:
        """Verify setnx respects TTL."""
        result = await redis_cache.setnx("setnx_ttl_key", "value", ttl=60)
        assert result is True
        ttl = await redis_cache.ttl("setnx_ttl_key")
        assert 0 < ttl <= 60

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_setnx_handles_connection_error(self) -> None:
        """Verify setnx returns False on connection error."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            result = await cache.setnx("any_key", "value")
            assert result is False
        finally:
            await cache.close()


class TestRedisCacheSetOperations:
    """Tests for set operations (sadd, srem, smembers, sismember)."""

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_sadd_adds_members(self, redis_cache: RedisCache) -> None:
        """Verify sadd adds members to set."""
        result = await redis_cache.sadd("myset", "member1", "member2")
        assert result == 2

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_sadd_returns_count_of_new_members(self, redis_cache: RedisCache) -> None:
        """Verify sadd returns count of newly added members."""
        await redis_cache.sadd("myset2", "member1")
        result = await redis_cache.sadd("myset2", "member1", "member2")
        assert result == 1

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_srem_removes_members(self, redis_cache: RedisCache) -> None:
        """Verify srem removes members from set."""
        await redis_cache.sadd("myset3", "a", "b", "c")
        result = await redis_cache.srem("myset3", "a", "b")
        assert result == 2
        members = await redis_cache.smembers("myset3")
        assert members == {"c"}

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_smembers_returns_all_members(self, redis_cache: RedisCache) -> None:
        """Verify smembers returns all set members."""
        await redis_cache.sadd("myset4", "x", "y", "z")
        members = await redis_cache.smembers("myset4")
        assert members == {"x", "y", "z"}

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_smembers_empty_set(self, redis_cache: RedisCache) -> None:
        """Verify smembers returns empty set for nonexistent key."""
        members = await redis_cache.smembers("nonexistent_set")
        assert members == set()

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_sismember_checks_membership(self, redis_cache: RedisCache) -> None:
        """Verify sismember checks set membership."""
        await redis_cache.sadd("myset5", "member")
        assert await redis_cache.sismember("myset5", "member") is True
        assert await redis_cache.sismember("myset5", "nonmember") is False

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_set_ops_handle_connection_error(self) -> None:
        """Verify set operations handle connection errors."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            assert await cache.sadd("key", "val") == 0
            assert await cache.srem("key", "val") == 0
            assert await cache.smembers("key") == set()
            assert await cache.sismember("key", "val") is False
        finally:
            await cache.close()


class TestRedisCacheSortedSetOperations:
    """Tests for sorted set operations (zadd, zrem, zrange, zrangebyscore, zcard)."""

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zadd_adds_member_with_score(self, redis_cache: RedisCache) -> None:
        """Verify zadd adds member with score."""
        result = await redis_cache.zadd("zset1", "member1", 1.0)
        assert result == 1

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zadd_updates_score(self, redis_cache: RedisCache) -> None:
        """Verify zadd updates score for existing member."""
        await redis_cache.zadd("zset2", "member", 1.0)
        result = await redis_cache.zadd("zset2", "member", 2.0)
        assert result == 0  # No new members added

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zrem_removes_member(self, redis_cache: RedisCache) -> None:
        """Verify zrem removes member from sorted set."""
        await redis_cache.zadd("zset3", "member", 1.0)
        result = await redis_cache.zrem("zset3", "member")
        assert result == 1

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zrange_returns_members_by_index(self, redis_cache: RedisCache) -> None:
        """Verify zrange returns members by index range."""
        await redis_cache.zadd("zset4", "a", 1.0)
        await redis_cache.zadd("zset4", "b", 2.0)
        await redis_cache.zadd("zset4", "c", 3.0)
        result = await redis_cache.zrange("zset4", 0, 1)
        assert result == ["a", "b"]

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zrangebyscore_returns_members_by_score(self, redis_cache: RedisCache) -> None:
        """Verify zrangebyscore returns members within score range."""
        await redis_cache.zadd("zset5", "low", 1.0)
        await redis_cache.zadd("zset5", "mid", 5.0)
        await redis_cache.zadd("zset5", "high", 10.0)
        result = await redis_cache.zrangebyscore("zset5", 2.0, 8.0)
        assert result == ["mid"]

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zcard_returns_cardinality(self, redis_cache: RedisCache) -> None:
        """Verify zcard returns sorted set size."""
        await redis_cache.zadd("zset6", "a", 1.0)
        await redis_cache.zadd("zset6", "b", 2.0)
        result = await redis_cache.zcard("zset6")
        assert result == 2

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_zcard_nonexistent(self, redis_cache: RedisCache) -> None:
        """Verify zcard returns 0 for nonexistent key."""
        result = await redis_cache.zcard("nonexistent_zset")
        assert result == 0

    @pytest.mark.usefixtures("_redis_connection_error")
    @pytest.mark.asyncio
    async def test_sorted_set_ops_handle_connection_error(self) -> None:
        """Verify sorted set operations handle connection errors."""
        cache = RedisCache(redis_url="redis://invalid:6379", service_name="test")
        try:
            assert await cache.zadd("key", "member", 1.0) == 0
            assert await cache.zrem("key", "member") == 0
            assert await cache.zrange("key", 0, -1) == []
            assert await cache.zrangebyscore("key", 0, 100) == []
            assert await cache.zcard("key") == 0
        finally:
            await cache.close()


class TestRedisCacheDistributedLock:
    """Tests for distributed lock operations."""

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, redis_cache: RedisCache) -> None:
        """Verify acquire_lock returns True for new lock."""
        result = await redis_cache.acquire_lock("mylock", "owner1", ttl_seconds=10, timeout_seconds=1)
        assert result is True

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_acquire_lock_fails_when_held(self, redis_cache: RedisCache) -> None:
        """Verify acquire_lock returns False when lock is already held."""
        await redis_cache.acquire_lock("held_lock", "owner1", ttl_seconds=60, timeout_seconds=0.05)
        result = await redis_cache.acquire_lock("held_lock", "owner2", ttl_seconds=60, timeout_seconds=0.05)
        assert result is False

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_release_lock_success(self, redis_cache: RedisCache) -> None:
        """Verify release_lock releases owned lock."""
        await redis_cache.acquire_lock("release_lock", "owner1", ttl_seconds=60, timeout_seconds=1)
        result = await redis_cache.release_lock("release_lock", "owner1")
        assert result is True
        # Lock should be released
        assert await redis_cache.is_locked("release_lock") is False

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_release_lock_wrong_owner(self, redis_cache: RedisCache) -> None:
        """Verify release_lock fails for wrong owner."""
        await redis_cache.acquire_lock("owned_lock", "owner1", ttl_seconds=60, timeout_seconds=1)
        result = await redis_cache.release_lock("owned_lock", "owner2")
        assert result is False

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_is_locked(self, redis_cache: RedisCache) -> None:
        """Verify is_locked returns correct state."""
        assert await redis_cache.is_locked("unlocked_key") is False
        await redis_cache.acquire_lock("locked_key", "owner", ttl_seconds=60, timeout_seconds=1)
        assert await redis_cache.is_locked("locked_key") is True

    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_distributed_lock_context_manager(self, redis_cache: RedisCache) -> None:
        """Verify distributed_lock context manager acquires and releases."""
        async with redis_cache.distributed_lock("ctx_lock", timeout_seconds=1, ttl_seconds=60):
            assert await redis_cache.is_locked("ctx_lock") is True
        assert await redis_cache.is_locked("ctx_lock") is False

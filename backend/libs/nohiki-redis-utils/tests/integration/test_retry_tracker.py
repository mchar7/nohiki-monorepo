"""Integration tests for Redis-backed retry tracker."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, cast

import pytest
from nohiki_redis_utils.retry_tracker import RedisRetryTracker

if TYPE_CHECKING:
    from redis.asyncio import Redis


class TestRedisRetryTrackerIntegration:
    """Tests requiring an actual Redis instance."""

    @pytest.fixture
    async def redis_client(self) -> Redis[str] | None:
        """Create Redis client for integration tests."""
        try:
            from redis.asyncio import Redis

            client: Redis[str] = Redis.from_url("redis://localhost:6379/15", decode_responses=True)
            await cast(Awaitable[bool], client.ping())
            yield client
            await client.flushdb()
            await client.aclose()
        except Exception:
            pytest.skip("Redis not available for integration tests")
            yield None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_retry_count_persists_across_tracker_instances(self, redis_client: Redis[str] | None) -> None:
        """Retry counts should persist across tracker instances (simulating restart)."""
        if redis_client is None:
            pytest.skip("Redis not available")

        tracker1 = RedisRetryTracker(redis_client, "integration_test", ttl_seconds=60)
        await tracker1.increment_retry_count("test_topic", 0, 100)
        await tracker1.increment_retry_count("test_topic", 0, 100)

        tracker2 = RedisRetryTracker(redis_client, "integration_test", ttl_seconds=60)
        count = await tracker2.get_retry_count("test_topic", 0, 100)

        assert count == 2, "Retry count should persist across tracker instances"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_increments_are_atomic(self, redis_client: Redis[str] | None) -> None:
        """Concurrent increments should not lose counts."""
        if redis_client is None:
            pytest.skip("Redis not available")

        tracker = RedisRetryTracker(redis_client, "integration_test", ttl_seconds=60)

        async def increment() -> int:
            return await tracker.increment_retry_count("concurrent_topic", 0, 100)

        results = await asyncio.gather(*[increment() for _ in range(100)])

        assert sorted(results) == list(range(1, 101)), "Concurrent increments should be atomic"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_ttl_prevents_indefinite_accumulation(self, redis_client: Redis[str] | None) -> None:
        """Keys should expire after TTL."""
        if redis_client is None:
            pytest.skip("Redis not available")

        tracker = RedisRetryTracker(redis_client, "ttl_test", ttl_seconds=1)
        await tracker.increment_retry_count("expiring_topic", 0, 100)

        count_before = await tracker.get_retry_count("expiring_topic", 0, 100)
        assert count_before == 1

        await asyncio.sleep(1.5)

        count_after = await tracker.get_retry_count("expiring_topic", 0, 100)
        assert count_after == 0, "Key should expire after TTL"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_first_failure_time_setnx_behavior(self, redis_client: Redis[str] | None) -> None:
        """First failure time should only be set once (SETNX)."""
        if redis_client is None:
            pytest.skip("Redis not available")

        tracker = RedisRetryTracker(redis_client, "setnx_test", ttl_seconds=60)

        await tracker.set_first_failure_time("topic", 0, 100)
        first_time = await tracker.get_first_failure_time("topic", 0, 100)

        await asyncio.sleep(0.1)
        await tracker.set_first_failure_time("topic", 0, 100)
        second_time = await tracker.get_first_failure_time("topic", 0, 100)

        assert first_time == second_time

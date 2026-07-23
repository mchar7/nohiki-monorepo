"""Integration tests for Redis-backed retry tracker."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from os import environ
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from nohiki_redis_utils.retry_tracker import RedisRetryTracker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from redis.asyncio import Redis

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


class TestRedisRetryTrackerIntegration:
    """Tests requiring an actual Redis instance."""

    @pytest.fixture
    async def retry_key_prefix(self, redis_client: Redis[bytes]) -> AsyncGenerator[str]:
        """Provide an isolated key prefix and remove only keys owned by the test."""
        worker_id = environ.get("PYTEST_XDIST_WORKER", "master")
        prefix = f"retry-tracker:{worker_id}:{uuid4().hex}"
        yield prefix
        keys = [key async for key in redis_client.scan_iter(match=f"{prefix}:*")]
        if keys:
            await redis_client.delete(*keys)

    @pytest.mark.asyncio
    async def test_retry_count_persists_across_tracker_instances(
        self,
        redis_client: Redis[bytes],
        retry_key_prefix: str,
    ) -> None:
        """Retry counts should persist across tracker instances (simulating restart)."""
        tracker1 = RedisRetryTracker(redis_client, retry_key_prefix, ttl_seconds=60)
        await tracker1.increment_retry_count("test_topic", 0, 100)
        await tracker1.increment_retry_count("test_topic", 0, 100)

        tracker2 = RedisRetryTracker(redis_client, retry_key_prefix, ttl_seconds=60)
        count = await tracker2.get_retry_count("test_topic", 0, 100)

        assert count == 2, "Retry count should persist across tracker instances"

    @pytest.mark.asyncio
    async def test_concurrent_increments_are_atomic(
        self,
        redis_client: Redis[bytes],
        retry_key_prefix: str,
    ) -> None:
        """Concurrent increments should not lose counts."""
        tracker = RedisRetryTracker(redis_client, retry_key_prefix, ttl_seconds=60)

        async def increment() -> int:
            return await tracker.increment_retry_count("concurrent_topic", 0, 100)

        async with asyncio.TaskGroup() as task_group:
            tasks = [task_group.create_task(increment()) for _ in range(100)]
        results = [task.result() for task in tasks]

        assert sorted(results) == list(range(1, 101)), "Concurrent increments should be atomic"

    @pytest.mark.asyncio
    async def test_ttl_prevents_indefinite_accumulation(
        self,
        redis_client: Redis[bytes],
        retry_key_prefix: str,
    ) -> None:
        """Keys should expire after TTL."""
        tracker = RedisRetryTracker(redis_client, retry_key_prefix, ttl_seconds=1)
        await tracker.increment_retry_count("expiring_topic", 0, 100)

        count_before = await tracker.get_retry_count("expiring_topic", 0, 100)
        assert count_before == 1

        async with asyncio.timeout(3):
            # Polling avoids mutating server-global keyspace-notification config.
            while (count_after := await tracker.get_retry_count("expiring_topic", 0, 100)) != 0:  # noqa: ASYNC110
                await asyncio.sleep(0.01)

        assert count_after == 0, "Key should expire after TTL"

    @pytest.mark.asyncio
    async def test_first_failure_time_setnx_behavior(
        self,
        redis_client: Redis[bytes],
        retry_key_prefix: str,
    ) -> None:
        """First failure time should only be set once (SETNX)."""
        tracker = RedisRetryTracker(redis_client, retry_key_prefix, ttl_seconds=60)

        expected_time = datetime(2020, 1, 1, tzinfo=UTC)
        key = f"{retry_key_prefix}:topic:0:100:first_failure"
        await redis_client.set(key, expected_time.isoformat(), ex=60)

        await tracker.set_first_failure_time("topic", 0, 100)

        assert await tracker.get_first_failure_time("topic", 0, 100) == expected_time

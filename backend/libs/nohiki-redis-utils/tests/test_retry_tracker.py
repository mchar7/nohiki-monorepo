"""Tests for Redis-backed retry tracker implementation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_redis_utils.retry_tracker import InMemoryRetryTracker, RedisRetryTracker


class TestInMemoryRetryTracker:
    """Tests for in-memory retry tracker (used for testing without Redis)."""

    @pytest.mark.asyncio
    async def test_get_retry_count_returns_zero_for_unknown_message(self) -> None:
        """Unknown messages should return retry count of 0."""
        tracker = InMemoryRetryTracker()
        count = await tracker.get_retry_count("topic", 0, 100)
        assert count == 0

    @pytest.mark.asyncio
    async def test_increment_from_zero_returns_one(self) -> None:
        """First increment should return 1."""
        tracker = InMemoryRetryTracker()
        count = await tracker.increment_retry_count("topic", 0, 100)
        assert count == 1

    @pytest.mark.asyncio
    async def test_increment_is_cumulative(self) -> None:
        """Multiple increments should accumulate."""
        tracker = InMemoryRetryTracker()

        count1 = await tracker.increment_retry_count("topic", 0, 100)
        count2 = await tracker.increment_retry_count("topic", 0, 100)
        count3 = await tracker.increment_retry_count("topic", 0, 100)

        assert count1 == 1
        assert count2 == 2
        assert count3 == 3

    @pytest.mark.asyncio
    async def test_different_messages_tracked_separately(self) -> None:
        """Different messages should have independent retry counts."""
        tracker = InMemoryRetryTracker()

        # Increment different messages
        await tracker.increment_retry_count("topic1", 0, 100)
        await tracker.increment_retry_count("topic1", 0, 100)
        await tracker.increment_retry_count("topic2", 0, 100)
        await tracker.increment_retry_count("topic1", 1, 100)

        # Verify independent tracking
        assert await tracker.get_retry_count("topic1", 0, 100) == 2
        assert await tracker.get_retry_count("topic2", 0, 100) == 1
        assert await tracker.get_retry_count("topic1", 1, 100) == 1

    @pytest.mark.asyncio
    async def test_clear_removes_retry_count(self) -> None:
        """Clear should remove retry count for a message."""
        tracker = InMemoryRetryTracker()

        await tracker.increment_retry_count("topic", 0, 100)
        await tracker.increment_retry_count("topic", 0, 100)
        assert await tracker.get_retry_count("topic", 0, 100) == 2

        await tracker.clear_retry_count("topic", 0, 100)
        assert await tracker.get_retry_count("topic", 0, 100) == 0

    @pytest.mark.asyncio
    async def test_clear_removes_first_failure_time(self) -> None:
        """Clear should also remove first failure time."""
        tracker = InMemoryRetryTracker()

        await tracker.set_first_failure_time("topic", 0, 100)
        assert await tracker.get_first_failure_time("topic", 0, 100) is not None

        await tracker.clear_retry_count("topic", 0, 100)
        assert await tracker.get_first_failure_time("topic", 0, 100) is None

    @pytest.mark.asyncio
    async def test_first_failure_time_only_set_once(self) -> None:
        """First failure time should only be set on first call (SETNX behavior)."""
        tracker = InMemoryRetryTracker()

        await tracker.set_first_failure_time("topic", 0, 100)
        first_time = await tracker.get_first_failure_time("topic", 0, 100)

        # Wait a bit and try to set again
        await asyncio.sleep(0.01)
        await tracker.set_first_failure_time("topic", 0, 100)
        second_time = await tracker.get_first_failure_time("topic", 0, 100)

        # Should be the same time (not updated)
        assert first_time == second_time

    @pytest.mark.asyncio
    async def test_first_failure_time_returns_none_for_unknown(self) -> None:
        """Unknown messages should return None for first failure time."""
        tracker = InMemoryRetryTracker()
        result = await tracker.get_first_failure_time("topic", 0, 100)
        assert result is None


class TestRedisRetryTracker:
    """Tests for Redis-backed retry tracker."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create a mock Redis client."""
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock(return_value=True)
        redis.delete = AsyncMock(return_value=1)
        redis.set = AsyncMock(return_value=True)

        # Mock pipeline
        pipeline = MagicMock()
        pipeline.incr = MagicMock(return_value=pipeline)
        pipeline.expire = MagicMock(return_value=pipeline)
        pipeline.delete = MagicMock(return_value=pipeline)
        pipeline.execute = AsyncMock(return_value=[1, True])
        redis.pipeline = MagicMock(return_value=pipeline)

        return redis

    @pytest.mark.asyncio
    async def test_get_retry_count_returns_zero_for_unknown(self, mock_redis: MagicMock) -> None:
        """Unknown messages should return retry count of 0."""
        mock_redis.get = AsyncMock(return_value=None)
        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)

        count = await tracker.get_retry_count("topic", 0, 100)

        assert count == 0
        mock_redis.get.assert_called_once_with("test:topic:0:100")

    @pytest.mark.asyncio
    async def test_get_retry_count_returns_stored_value(self, mock_redis: MagicMock) -> None:
        """Should return stored retry count."""
        mock_redis.get = AsyncMock(return_value="5")
        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)

        count = await tracker.get_retry_count("topic", 0, 100)

        assert count == 5

    @pytest.mark.asyncio
    async def test_increment_uses_pipeline_for_atomicity(self, mock_redis: MagicMock) -> None:
        """Increment should use pipeline for atomic INCR + EXPIRE."""
        pipeline = mock_redis.pipeline.return_value
        pipeline.execute = AsyncMock(return_value=[3, True])

        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)
        count = await tracker.increment_retry_count("topic", 0, 100)

        assert count == 3
        mock_redis.pipeline.assert_called_once()
        pipeline.incr.assert_called_once_with("test:topic:0:100")
        pipeline.expire.assert_called_once_with("test:topic:0:100", 3600)
        pipeline.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_deletes_both_keys(self, mock_redis: MagicMock) -> None:
        """Clear should delete both retry count and first failure keys."""
        pipeline = mock_redis.pipeline.return_value
        pipeline.execute = AsyncMock(return_value=[1, 1])

        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)
        await tracker.clear_retry_count("topic", 0, 100)

        pipeline.delete.assert_any_call("test:topic:0:100")
        pipeline.delete.assert_any_call("test:topic:0:100:first_failure")

    @pytest.mark.asyncio
    async def test_set_first_failure_time_is_atomic_set_nx_ex(self, mock_redis: MagicMock) -> None:
        """First failure timestamp creation and expiry are one atomic Redis operation."""
        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)

        await tracker.set_first_failure_time("topic", 0, 100)

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args.args[0] == "test:topic:0:100:first_failure"
        datetime.fromisoformat(call_args.args[1])
        assert call_args.kwargs == {"nx": True, "ex": 3600}

    @pytest.mark.asyncio
    async def test_existing_first_failure_time_is_left_unchanged(self, mock_redis: MagicMock) -> None:
        """A failed NX result does not overwrite or extend an existing failure window."""
        mock_redis.set = AsyncMock(return_value=None)
        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)

        await tracker.set_first_failure_time("topic", 0, 100)

        mock_redis.set.assert_awaited_once()
        assert mock_redis.set.call_args.kwargs == {"nx": True, "ex": 3600}
        mock_redis.expire.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_first_failure_time_parses_iso_timestamp(self, mock_redis: MagicMock) -> None:
        """Should parse ISO timestamp from Redis."""
        expected_time = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        mock_redis.get = AsyncMock(return_value=expected_time.isoformat())

        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)
        result = await tracker.get_first_failure_time("topic", 0, 100)

        assert result == expected_time
        mock_redis.get.assert_called_once_with("test:topic:0:100:first_failure")

    @pytest.mark.asyncio
    async def test_get_first_failure_time_returns_none_when_missing(self, mock_redis: MagicMock) -> None:
        """Should return None when key doesn't exist."""
        mock_redis.get = AsyncMock(return_value=None)

        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=3600)
        result = await tracker.get_first_failure_time("topic", 0, 100)

        assert result is None

    @pytest.mark.asyncio
    async def test_key_prefix_is_applied(self, mock_redis: MagicMock) -> None:
        """Custom key prefix should be applied to all keys."""
        tracker = RedisRetryTracker(mock_redis, "custom_prefix", ttl_seconds=3600)

        await tracker.get_retry_count("my_topic", 5, 999)

        mock_redis.get.assert_called_once_with("custom_prefix:my_topic:5:999")

    @pytest.mark.asyncio
    async def test_ttl_is_configurable(self, mock_redis: MagicMock) -> None:
        """TTL should be configurable."""
        pipeline = mock_redis.pipeline.return_value
        pipeline.execute = AsyncMock(return_value=[1, True])

        tracker = RedisRetryTracker(mock_redis, "test", ttl_seconds=7200)
        await tracker.increment_retry_count("topic", 0, 100)

        pipeline.expire.assert_called_once_with("test:topic:0:100", 7200)

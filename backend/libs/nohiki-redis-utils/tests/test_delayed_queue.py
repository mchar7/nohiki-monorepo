"""Tests for the DelayedTaskQueue implementation."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from unittest.mock import AsyncMock

import pytest
from nohiki_redis_utils import RedisCache
from nohiki_redis_utils.delayed_queue import ClaimedTask, DelayedTaskQueue, QueueStats


class CacheProtocol(Protocol):
    """Protocol for cache implementations used by DelayedTaskQueue."""

    async def get(self, key: str) -> object: ...
    async def set(self, key: str, value: object, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    async def setnx(self, key: str, value: object, ttl: int | None = None) -> bool: ...
    async def zadd(self, key: str, member: str, score: float) -> int: ...
    async def zrem(self, key: str, member: str) -> int: ...
    async def zrange(self, key: str, start: int, stop: int) -> list[str]: ...
    async def zrangebyscore(
        self,
        key: str,
        min_score: float,
        max_score: float,
        offset: int = 0,
        count: int = -1,
    ) -> list[str]: ...
    async def zcard(self, key: str) -> int: ...
    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> list[str]: ...


@dataclass
class SamplePayload:
    """Sample payload for queue testing."""

    user_id: str
    data: str

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> SamplePayload:
        """Deserialize from JSON string."""
        return cls(**json.loads(s))


class MockCache:
    """Mock cache implementation for testing DelayedTaskQueue."""

    def __init__(self) -> None:
        """Initialize mock cache with in-memory sorted sets."""
        self._data: dict[str, object] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}  # key -> {member: score}

    async def get(self, key: str) -> object:
        """Get value from cache."""
        await self._ensure_async()
        return self._data.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None) -> None:
        """Set value in cache."""
        await self._ensure_async()
        _ = ttl  # TTL is intentionally ignored in mock
        self._data[key] = value

    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        await self._ensure_async()
        self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        await self._ensure_async()
        return key in self._data

    async def setnx(self, key: str, value: object, ttl: int | None = None) -> bool:
        """Set if not exists."""
        await self._ensure_async()
        _ = ttl  # TTL is intentionally ignored in mock
        if key in self._data:
            return False
        self._data[key] = value
        return True

    async def zadd(self, key: str, member: str, score: float) -> int:
        """Add to sorted set."""
        await self._ensure_async()
        if key not in self._sorted_sets:
            self._sorted_sets[key] = {}

        is_new = member not in self._sorted_sets[key]
        self._sorted_sets[key][member] = score
        return 1 if is_new else 0

    async def zrem(self, key: str, member: str) -> int:
        """Remove from sorted set."""
        await self._ensure_async()
        if key not in self._sorted_sets:
            return 0
        if member in self._sorted_sets[key]:
            del self._sorted_sets[key][member]
            return 1
        return 0

    async def zrange(self, key: str, start: int, stop: int) -> list[str]:
        """Get range by index."""
        await self._ensure_async()
        if key not in self._sorted_sets:
            return []

        sorted_members = sorted(self._sorted_sets[key].items(), key=lambda x: x[1])
        members = [m for m, _ in sorted_members]

        # Handle negative indices
        stop = len(members) + stop + 1 if stop < 0 else stop + 1
        return members[start:stop]

    async def zrangebyscore(
        self,
        key: str,
        min_score: float,
        max_score: float,
        offset: int = 0,
        count: int = -1,
    ) -> list[str]:
        """Get range by score."""
        await self._ensure_async()
        if key not in self._sorted_sets:
            return []

        result = [
            m for m, s in sorted(self._sorted_sets[key].items(), key=lambda x: x[1]) if min_score <= s <= max_score
        ]

        if count > 0:
            return result[offset : offset + count]
        return result[offset:]

    async def zcard(self, key: str) -> int:
        """Get cardinality."""
        await self._ensure_async()
        if key not in self._sorted_sets:
            return 0
        return len(self._sorted_sets[key])

    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> list[str]:
        """Execute Lua script - simulated for testing."""
        await self._ensure_async()

        if self._is_claim_script(script, keys, args):
            return self._execute_claim_script(keys, args)

        if self._is_recover_script(script, keys, args):
            return self._execute_recover_script(keys, args)

        return []

    @staticmethod
    def _is_claim_script(script: str, keys: list[str], args: list[str]) -> bool:
        """Check if script is a claim script."""
        return "LIMIT" in script and "recovered" not in script and len(keys) == 2 and len(args) == 2

    @staticmethod
    def _is_recover_script(script: str, keys: list[str], args: list[str]) -> bool:
        """Check if script is a recover script."""
        return "recovered" in script and len(keys) == 2 and len(args) == 2

    def _execute_claim_script(self, keys: list[str], args: list[str]) -> list[str]:
        """Execute claim script: move due tasks from pending to processing."""
        pending_key = keys[0]
        processing_key = keys[1]
        now = float(args[0])
        limit = int(args[1])

        if pending_key not in self._sorted_sets:
            return []

        due_members = self._get_due_members(pending_key, now, limit)
        return self._move_to_processing(due_members, pending_key, processing_key, now)

    def _get_due_members(self, pending_key: str, now: float, limit: int) -> list[str]:
        """Get members that are due for processing."""
        sorted_items = sorted(self._sorted_sets[pending_key].items(), key=lambda x: x[1])
        return [m for m, s in sorted_items if s <= now][:limit]

    def _move_to_processing(self, members: list[str], from_key: str, to_key: str, score: float) -> list[str]:
        """Move members from one sorted set to another."""
        claimed = []
        for member in members:
            del self._sorted_sets[from_key][member]
            if to_key not in self._sorted_sets:
                self._sorted_sets[to_key] = {}
            self._sorted_sets[to_key][member] = score
            claimed.append(member)
        return claimed

    def _execute_recover_script(self, keys: list[str], args: list[str]) -> list[str]:
        """Execute recover script: move stuck tasks from processing to pending."""
        processing_key = keys[0]
        pending_key = keys[1]
        timeout_threshold = float(args[0])
        now = float(args[1])

        if processing_key not in self._sorted_sets:
            return ["0"]

        stuck_members = self._get_stuck_members(processing_key, timeout_threshold)
        self._move_to_pending(stuck_members, processing_key, pending_key, now)
        return [str(len(stuck_members))]

    def _get_stuck_members(self, processing_key: str, timeout_threshold: float) -> list[str]:
        """Get members that are stuck in processing."""
        return [m for m, s in self._sorted_sets[processing_key].items() if s <= timeout_threshold]

    def _move_to_pending(self, members: list[str], from_key: str, to_key: str, score: float) -> None:
        """Move stuck members back to pending."""
        for member in members:
            del self._sorted_sets[from_key][member]
            if to_key not in self._sorted_sets:
                self._sorted_sets[to_key] = {}
            self._sorted_sets[to_key][member] = score

    @staticmethod
    async def _ensure_async() -> None:
        """Ensure method is actually async by yielding control."""
        import asyncio

        await asyncio.sleep(0)


@pytest.fixture
def mock_cache() -> MockCache:
    """Create a mock cache for testing."""
    return MockCache()


@pytest.fixture
def queue(mock_cache: MockCache) -> DelayedTaskQueue[SamplePayload]:
    """Create a DelayedTaskQueue for testing."""
    return DelayedTaskQueue[SamplePayload](
        cache=cast(Any, mock_cache),
        queue_name="test-queue",
        serializer=SamplePayload.to_json,
        deserializer=SamplePayload.from_json,
        processing_timeout_seconds=300,
    )


class TestDelayedTaskQueueAdd:
    """Tests for adding tasks to the queue."""

    @pytest.mark.asyncio
    async def test_add_and_claim_due_task(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Add a task and claim it when due."""
        payload = SamplePayload(user_id="user-123", data="test data")
        run_at = datetime.now(UTC) - timedelta(seconds=1)  # Already due

        await queue.add("task-1", payload, run_at=run_at)

        claimed = await queue.claim_due(limit=10)

        assert len(claimed) == 1
        assert claimed[0].task_id == "task-1"
        assert claimed[0].payload.user_id == "user-123"
        assert claimed[0].payload.data == "test data"

    @pytest.mark.asyncio
    async def test_add_replaces_existing_task(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Adding a task with same ID replaces the existing one."""
        payload1 = SamplePayload(user_id="user-1", data="first")
        payload2 = SamplePayload(user_id="user-2", data="second")
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        await queue.add("task-1", payload1, run_at=run_at)
        await queue.add("task-1", payload2, run_at=run_at)

        # Should only have one task
        stats = await queue.get_stats()
        assert stats.pending_count == 1

        claimed = await queue.claim_due()
        assert len(claimed) == 1
        assert claimed[0].payload.user_id == "user-2"


class TestDelayedTaskQueueClaim:
    """Tests for claiming tasks from the queue."""

    @pytest.mark.asyncio
    async def test_claim_respects_run_at(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Tasks are not claimed before their scheduled time."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) + timedelta(hours=1)  # Future

        await queue.add("task-1", payload, run_at=run_at)

        claimed = await queue.claim_due(limit=10)

        assert len(claimed) == 0

    @pytest.mark.asyncio
    async def test_claim_limit(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Limit parameter is respected when claiming."""
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        for i in range(5):
            payload = SamplePayload(user_id=f"user-{i}", data=f"data-{i}")
            await queue.add(f"task-{i}", payload, run_at=run_at)

        claimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due(limit=2)

        assert len(claimed) == 2

    @pytest.mark.asyncio
    async def test_claim_moves_to_processing(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Claiming moves tasks from pending to processing."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        await queue.add("task-1", payload, run_at=run_at)

        stats_before: QueueStats = await queue.get_stats()
        assert stats_before.pending_count == 1
        assert stats_before.processing_count == 0

        await queue.claim_due(limit=10)

        stats_after: QueueStats = await queue.get_stats()
        assert stats_after.pending_count == 0
        assert stats_after.processing_count == 1


class TestDelayedTaskQueueComplete:
    """Tests for completing tasks."""

    @pytest.mark.asyncio
    async def test_complete_with_reschedule(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Task is rescheduled after complete with next_run_at."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=1)
        next_run = datetime.now(UTC) + timedelta(hours=24)

        await queue.add("task-1", payload, run_at=run_at)
        claimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due()

        await queue.complete(claimed[0], next_run_at=next_run)

        stats: QueueStats = await queue.get_stats()
        assert stats.pending_count == 1  # Back in pending
        assert stats.processing_count == 0

    @pytest.mark.asyncio
    async def test_complete_without_reschedule(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Task is removed after complete without next_run_at."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        await queue.add("task-1", payload, run_at=run_at)
        claimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due()

        await queue.complete(claimed[0])

        stats: QueueStats = await queue.get_stats()
        assert stats.pending_count == 0
        assert stats.processing_count == 0


class TestDelayedTaskQueueFail:
    """Tests for failing tasks."""

    @pytest.mark.asyncio
    async def test_fail_returns_to_pending(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Failed task is returned to pending for retry."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        await queue.add("task-1", payload, run_at=run_at)
        claimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due()

        await queue.fail(claimed[0])

        stats: QueueStats = await queue.get_stats()
        assert stats.pending_count == 1  # Back in pending
        assert stats.processing_count == 0

        # Should be immediately claimable again
        reclaimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due()
        assert len(reclaimed) == 1
        assert reclaimed[0].task_id == "task-1"


class TestDelayedTaskQueueRemove:
    """Tests for removing tasks."""

    @pytest.mark.asyncio
    async def test_remove_from_pending(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Remove works for pending tasks."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) + timedelta(hours=1)

        await queue.add("task-1", payload, run_at=run_at)

        result = await queue.remove("task-1")

        assert result is True
        stats: QueueStats = await queue.get_stats()
        assert stats.pending_count == 0

    @pytest.mark.asyncio
    async def test_remove_from_processing(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Remove works for processing tasks."""
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        await queue.add("task-1", payload, run_at=run_at)
        await queue.claim_due()

        result = await queue.remove("task-1")

        assert result is True
        stats: QueueStats = await queue.get_stats()
        assert stats.processing_count == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Remove returns False for nonexistent task."""
        result = await queue.remove("nonexistent")
        assert result is False


class TestDelayedTaskQueueRecoverStuck:
    """Tests for recovering stuck tasks."""

    @pytest.mark.asyncio
    async def test_recover_stuck(self, mock_cache: MockCache) -> None:
        """Stuck tasks are recovered after timeout."""
        # Use short timeout for testing
        queue: DelayedTaskQueue[SamplePayload] = DelayedTaskQueue[SamplePayload](
            cache=cast(Any, mock_cache),
            queue_name="test-queue",
            serializer=SamplePayload.to_json,
            deserializer=SamplePayload.from_json,
            processing_timeout_seconds=1,  # 1 second timeout
        )

        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=10)

        await queue.add("task-1", payload, run_at=run_at)

        # Claim and simulate being stuck
        claimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due()
        assert len(claimed) == 1

        # Manually set claimed_at to be old (simulate time passing)
        processing_key = queue.processing_key
        processing_set = mock_cache._sorted_sets.get(processing_key, {})
        for member in processing_set:
            processing_set[member] = (datetime.now(UTC) - timedelta(seconds=10)).timestamp()

        # Recover
        recovered: int = await queue.recover_stuck()

        assert recovered == 1
        stats: QueueStats = await queue.get_stats()
        assert stats.pending_count == 1
        assert stats.processing_count == 0


class TestDelayedTaskQueueStats:
    """Tests for queue statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, queue: DelayedTaskQueue[SamplePayload]) -> None:
        """Stats reflect queue state correctly."""
        stats_empty = await queue.get_stats()
        assert stats_empty.pending_count == 0
        assert stats_empty.processing_count == 0

        # Add pending tasks
        for i in range(3):
            payload = SamplePayload(user_id=f"user-{i}", data=f"data-{i}")
            run_at = datetime.now(UTC) - timedelta(seconds=1)
            await queue.add(f"task-{i}", payload, run_at=run_at)

        stats_with_pending: QueueStats = await queue.get_stats()
        assert stats_with_pending.pending_count == 3
        assert stats_with_pending.processing_count == 0

        # Claim some
        await queue.claim_due(limit=2)

        stats_mixed: QueueStats = await queue.get_stats()
        assert stats_mixed.pending_count == 1
        assert stats_mixed.processing_count == 2


class TestDelayedTaskQueueAtomicClaim:
    """Tests for atomic claiming behavior."""

    @pytest.mark.asyncio
    async def test_atomic_claim_uses_lua_script(self) -> None:
        """Verify that claim_due uses eval_script for atomicity."""
        mock_cache = AsyncMock(spec=RedisCache)
        mock_cache.eval_script = AsyncMock(return_value=[])
        mock_cache.zrange = AsyncMock(return_value=[])

        queue: DelayedTaskQueue[SamplePayload] = DelayedTaskQueue[SamplePayload](
            cache=cast(Any, mock_cache),
            queue_name="test-queue",
            serializer=SamplePayload.to_json,
            deserializer=SamplePayload.from_json,
        )

        await queue.claim_due(limit=10)

        # Verify eval_script was called
        mock_cache.eval_script.assert_called_once()
        call_args = mock_cache.eval_script.call_args

        # call_args[0] contains positional args (script)
        # call_args.kwargs contains keyword args (keys, args)
        script = call_args[0][0]
        keys = call_args.kwargs["keys"]
        script_args = call_args.kwargs["args"]

        # Verify keys passed
        assert keys == ["test-queue:pending", "test-queue:processing"]

        # Verify script contains claim logic
        assert "ZRANGEBYSCORE" in script
        assert "ZREM" in script
        assert "ZADD" in script

        # Verify args (now timestamp, limit)
        assert len(script_args) == 2


class TestDelayedTaskQueueSerialization:
    """Tests for payload serialization/deserialization."""

    @pytest.mark.asyncio
    async def test_complex_payload(self, mock_cache: MockCache) -> None:
        """Test with complex payload data."""

        @dataclass
        class ComplexPayload:
            id: str
            nested: dict[str, object]
            items: list[str]

            def to_json(self) -> str:
                return json.dumps(asdict(self))

            @classmethod
            def from_json(cls, s: str) -> ComplexPayload:
                return cls(**json.loads(s))

        queue: DelayedTaskQueue[ComplexPayload] = DelayedTaskQueue[ComplexPayload](
            cache=cast(Any, mock_cache),
            queue_name="complex-queue",
            serializer=ComplexPayload.to_json,
            deserializer=ComplexPayload.from_json,
        )

        payload = ComplexPayload(
            id="test-123",
            nested={"key": "value", "number": 42},
            items=["a", "b", "c"],
        )
        run_at = datetime.now(UTC) - timedelta(seconds=1)

        await queue.add("task-1", payload, run_at=run_at)
        claimed: list[ClaimedTask[ComplexPayload]] = await queue.claim_due()

        assert len(claimed) == 1
        assert claimed[0].payload.id == "test-123"
        assert claimed[0].payload.nested == {"key": "value", "number": 42}
        assert claimed[0].payload.items == ["a", "b", "c"]


class TestClaimedTaskDataclass:
    """Tests for the ClaimedTask dataclass."""

    def test_claimed_task_is_frozen(self) -> None:
        """ClaimedTask should be immutable."""
        assert dataclasses.is_dataclass(ClaimedTask)
        params = getattr(ClaimedTask, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestQueueStatsDataclass:
    """Tests for the QueueStats dataclass."""

    def test_queue_stats_fields(self) -> None:
        """QueueStats has expected fields."""
        stats = QueueStats(pending_count=5, processing_count=3)

        assert stats.pending_count == 5
        assert stats.processing_count == 3


class TestDelayedTaskQueueEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_remove_ignores_malformed_json_in_queue(self, mock_cache: MockCache) -> None:
        """Remove should skip malformed JSON members without crashing."""
        queue: DelayedTaskQueue[SamplePayload] = DelayedTaskQueue[SamplePayload](
            cache=cast(Any, mock_cache),
            queue_name="test-queue",
            serializer=SamplePayload.to_json,
            deserializer=SamplePayload.from_json,
        )

        # Manually inject malformed JSON into the pending set
        await mock_cache.zadd("test-queue:pending", "not valid json", 100.0)
        await mock_cache.zadd("test-queue:pending", '{"missing": "task_id"}', 101.0)

        # Remove should not find the task and return False without crashing
        result = await queue.remove("nonexistent-task")

        assert result is False

    @pytest.mark.asyncio
    async def test_claim_skips_malformed_members(self, mock_cache: MockCache) -> None:
        """Claim should skip members with malformed JSON and log warning."""
        queue = DelayedTaskQueue[SamplePayload](
            cache=cast(Any, mock_cache),
            queue_name="test-queue",
            serializer=SamplePayload.to_json,
            deserializer=SamplePayload.from_json,
        )

        # Add a valid task first
        payload = SamplePayload(user_id="user-123", data="test")
        run_at = datetime.now(UTC) - timedelta(seconds=10)
        await queue.add("valid-task", payload, run_at=run_at)

        # Manually inject malformed JSON directly into sorted set
        # This bypasses normal add() to simulate corrupted data
        mock_cache._sorted_sets["test-queue:pending"]["invalid json here"] = (
            datetime.now(UTC) - timedelta(seconds=5)
        ).timestamp()

        # Claim should skip the malformed member and return the valid one
        claimed: list[ClaimedTask[SamplePayload]] = await queue.claim_due(limit=10)

        # Should have claimed the valid task (malformed one skipped)
        assert len(claimed) == 1
        assert claimed[0].task_id == "valid-task"

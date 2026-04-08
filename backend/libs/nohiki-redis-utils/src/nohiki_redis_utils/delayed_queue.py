"""Distributed delayed task queue with atomic claiming via Redis."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from .redis_cache import RedisCache

logger = get_logger(__name__)


# Lua script for atomically claiming due tasks
# Moves tasks from pending to processing set in a single operation
_CLAIM_SCRIPT = """
local pending_key = KEYS[1]
local processing_key = KEYS[2]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])

local due = redis.call('ZRANGEBYSCORE', pending_key, '-inf', now, 'LIMIT', 0, limit)

if #due == 0 then
    return {}
end

local claimed = {}
for _, member in ipairs(due) do
    redis.call('ZREM', pending_key, member)
    redis.call('ZADD', processing_key, now, member)
    table.insert(claimed, member)
end

return claimed
"""

# Lua script for recovering stuck tasks
# Moves tasks that have been in processing too long back to pending
_RECOVER_STUCK_SCRIPT = """
local processing_key = KEYS[1]
local pending_key = KEYS[2]
local timeout_threshold = tonumber(ARGV[1])
local now = tonumber(ARGV[2])

local stuck = redis.call('ZRANGEBYSCORE', processing_key, '-inf', timeout_threshold)

local recovered = 0
for _, member in ipairs(stuck) do
    redis.call('ZREM', processing_key, member)
    redis.call('ZADD', pending_key, now, member)
    recovered = recovered + 1
end

return recovered
"""


@dataclass(frozen=True, slots=True)
class ClaimedTask[T]:
    """A task that has been claimed from the queue for processing."""

    task_id: str
    payload: T
    claimed_at: datetime
    raw_member: str  # The JSON string stored in Redis (used for complete/fail)


@dataclass(frozen=True, slots=True)
class QueueStats:
    """Statistics for a delayed task queue."""

    pending_count: int
    processing_count: int


class DelayedTaskQueue[T]:
    """Distributed delayed task queue with atomic claiming.

    Uses Redis sorted sets for O(log N) scheduling and Lua scripts
    for atomic claim operations to prevent duplicate processing.

    Data Model:
        {queue_name}:pending (Sorted Set)
            score: run_at (unix timestamp)
            member: JSON {task_id, payload, ...}

        {queue_name}:processing (Sorted Set)
            score: claimed_at (unix timestamp)
            member: JSON {task_id, payload, ...}

    Args:
        cache: RedisCache instance (use create_cache())
        queue_name: Unique name for this queue (e.g., "scrape-schedules")
        serializer: Function to convert payload T to JSON string
        deserializer: Function to convert JSON string to payload T
        processing_timeout_seconds: Tasks in processing longer than this
            are considered stuck and can be recovered (default: 300)

    Example:
        @dataclass
        class MyPayload:
            user_id: str
            data: dict

            def to_json(self) -> str:
                return json.dumps(asdict(self))

            @classmethod
            def from_json(cls, s: str) -> "MyPayload":
                d = json.loads(s)
                return cls(**d)

        queue = DelayedTaskQueue[MyPayload](
            cache=create_cache("my-service"),
            queue_name="my-tasks",
            serializer=MyPayload.to_json,
            deserializer=MyPayload.from_json,
        )

        await queue.add("task-1", payload, run_at=datetime.now(UTC) + timedelta(hours=1))

        claimed = await queue.claim_due(limit=10)
        for task in claimed:
            try:
                await process(task.payload)
                await queue.complete(task, next_run_at=...)
            except Exception:
                await queue.fail(task)

    """

    def __init__(
        self,
        cache: RedisCache,
        queue_name: str,
        serializer: Callable[[T], str],
        deserializer: Callable[[str], T],
        processing_timeout_seconds: int = 300,
    ) -> None:
        """Initialize the delayed task queue.

        Args:
            cache: RedisCache instance (use create_cache())
            queue_name: Unique name for this queue
            serializer: Function to convert payload T to JSON string
            deserializer: Function to convert JSON string to payload T
            processing_timeout_seconds: Timeout for stuck task detection

        """
        self._cache = cache
        self._queue_name = queue_name
        self._serializer = serializer
        self._deserializer = deserializer
        self._processing_timeout_seconds = processing_timeout_seconds

    @property
    def pending_key(self) -> str:
        """Redis key for the pending sorted set."""
        return f"{self._queue_name}:pending"

    @property
    def processing_key(self) -> str:
        """Redis key for the processing sorted set."""
        return f"{self._queue_name}:processing"

    def _make_member(self, task_id: str, payload: T) -> str:
        """Create the JSON member string for storage in Redis."""
        serialized_payload = self._serializer(payload)
        return json.dumps({"task_id": task_id, "payload": serialized_payload})

    def _parse_member(self, member: str) -> tuple[str, T]:
        """Parse the JSON member string from Redis."""
        data = json.loads(member)
        task_id = data["task_id"]
        payload = self._deserializer(data["payload"])
        return task_id, payload

    async def add(
        self,
        task_id: str,
        payload: T,
        run_at: datetime,
    ) -> None:
        """Add or update a task to run at the specified time.

        If a task with the same task_id already exists, it will be replaced.

        Args:
            task_id: Unique identifier for this task
            payload: The payload data (will be serialized)
            run_at: When the task should become due (timezone-aware datetime)

        """
        # First, remove any existing task with this ID
        await self.remove(task_id)

        # Create the member and add to pending set
        member = self._make_member(task_id, payload)
        score = run_at.timestamp()

        await self._cache.zadd(self.pending_key, member, score)

        logger.info(
            "Added task to delayed queue",
            queue=self._queue_name,
            task_id=task_id,
            run_at=run_at.isoformat(),
        )

    async def _remove_from_set(self, set_key: str, task_id: str, set_name: str) -> bool:
        """Remove a task from a specific sorted set by task_id."""
        members = await self._cache.zrange(set_key, 0, -1)
        for member in members:
            if self._member_matches_task_id(member, task_id):
                result = await self._cache.zrem(set_key, member)
                if result > 0:
                    logger.info(
                        "Removed task from queue",
                        set_name=set_name,
                        queue=self._queue_name,
                        task_id=task_id,
                    )
                    return True
        return False

    def _member_matches_task_id(self, member: str, task_id: str) -> bool:
        """Check if a member JSON matches the given task_id."""
        try:
            parsed_task_id, _ = self._parse_member(member)
        except json.JSONDecodeError, KeyError:
            return False
        return parsed_task_id == task_id

    async def remove(self, task_id: str) -> bool:
        """Remove a task from the queue.

        Searches both pending and processing sets.

        Args:
            task_id: The task ID to remove

        Returns:
            True if a task was removed, False if not found

        """
        removed_from_pending = await self._remove_from_set(self.pending_key, task_id, "pending")
        removed_from_processing = await self._remove_from_set(self.processing_key, task_id, "processing")
        return removed_from_pending or removed_from_processing

    async def claim_due(self, limit: int = 100) -> list[ClaimedTask[T]]:
        """Atomically claim up to `limit` tasks that are due.

        Tasks are moved from pending to processing set atomically
        using a Lua script to prevent duplicate claims across pods.

        Args:
            limit: Maximum number of tasks to claim

        Returns:
            List of claimed tasks (may be empty if none due)

        """
        now = time.time()
        now_dt = datetime.fromtimestamp(now, tz=UTC)

        # Execute Lua script for atomic claim
        claimed_members = await self._cache.eval_script(
            _CLAIM_SCRIPT,
            keys=[self.pending_key, self.processing_key],
            args=[str(int(now)), str(limit)],
        )

        claimed_tasks: list[ClaimedTask[T]] = []
        for member in claimed_members:
            try:
                task_id, payload = self._parse_member(member)
                claimed_task = ClaimedTask(
                    task_id=task_id,
                    payload=payload,
                    claimed_at=now_dt,
                    raw_member=member,
                )
                claimed_tasks.append(claimed_task)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(
                    "Failed to parse claimed task member",
                    queue=self._queue_name,
                    member=member,
                    error=str(e),
                )
                continue

        if claimed_tasks:
            logger.info(
                "Claimed tasks from delayed queue",
                queue=self._queue_name,
                count=len(claimed_tasks),
                task_ids=[t.task_id for t in claimed_tasks],
            )

        return claimed_tasks

    async def complete(
        self,
        task: ClaimedTask[T],
        next_run_at: datetime | None = None,
    ) -> None:
        """Mark a task as complete.

        If next_run_at is provided, the task is rescheduled to that time.
        Otherwise, the task is removed from the queue entirely.

        Args:
            task: The claimed task to complete
            next_run_at: Optional next run time for recurring tasks

        """
        # Remove from processing set
        await self._cache.zrem(self.processing_key, task.raw_member)

        if next_run_at is not None:
            # Reschedule: add back to pending with new run time
            member = self._make_member(task.task_id, task.payload)
            score = next_run_at.timestamp()
            await self._cache.zadd(self.pending_key, member, score)

            logger.info(
                "Completed and rescheduled task",
                queue=self._queue_name,
                task_id=task.task_id,
                next_run_at=next_run_at.isoformat(),
            )
        else:
            logger.info(
                "Completed task (no reschedule)",
                queue=self._queue_name,
                task_id=task.task_id,
            )

    async def fail(self, task: ClaimedTask[T]) -> None:
        """Mark a task as failed.

        The task is returned to the pending set with the current timestamp,
        making it immediately eligible for reclaiming.

        Args:
            task: The claimed task that failed

        """
        # Use int timestamp for consistency with claim_due() which also uses int
        now = int(time.time())

        # Remove from processing
        await self._cache.zrem(self.processing_key, task.raw_member)

        # Add back to pending with current timestamp (immediate retry)
        await self._cache.zadd(self.pending_key, task.raw_member, float(now))

        logger.info(
            "Failed task returned to pending",
            queue=self._queue_name,
            task_id=task.task_id,
        )

    async def recover_stuck(self) -> int:
        """Recover tasks stuck in the processing state.

        Tasks that have been in processing longer than processing_timeout_seconds
        are moved back to pending for retry.

        Should be called periodically (e.g., every 5 minutes via cron).

        Returns:
            Number of tasks recovered

        """
        now = time.time()
        timeout_threshold = now - self._processing_timeout_seconds

        # Execute Lua script for atomic recovery
        result = await self._cache.eval_script(
            _RECOVER_STUCK_SCRIPT,
            keys=[self.processing_key, self.pending_key],
            args=[str(int(timeout_threshold)), str(int(now))],
        )

        # Result is a list with one element (the count)
        recovered = int(result[0]) if result else 0

        if recovered > 0:
            logger.info(
                "Recovered stuck tasks",
                queue=self._queue_name,
                count=recovered,
                timeout_seconds=self._processing_timeout_seconds,
            )

        return recovered

    async def get_stats(self) -> QueueStats:
        """Get queue statistics.

        Returns:
            QueueStats with pending and processing counts

        """
        pending_count = await self._cache.zcard(self.pending_key)
        processing_count = await self._cache.zcard(self.processing_key)

        return QueueStats(
            pending_count=pending_count,
            processing_count=processing_count,
        )

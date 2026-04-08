"""Redis-backed retry tracking for Kafka message processing.

Persistent retry tracking that survives service restarts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

    type RedisClient = AsyncRedis[bytes]

logger = get_logger(__name__)


class RetryTrackerProtocol(Protocol):
    """Protocol defining the retry tracker interface."""

    async def get_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Get current retry count for a message."""
        ...

    async def increment_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Increment and return retry count for a message."""
        ...

    async def clear_retry_count(self, topic: str, partition: int, offset: int) -> None:
        """Clear retry count after successful processing."""
        ...

    async def get_first_failure_time(self, topic: str, partition: int, offset: int) -> datetime | None:
        """Get timestamp of first failure for a message."""
        ...

    async def set_first_failure_time(self, topic: str, partition: int, offset: int) -> None:
        """Set first failure timestamp (only if not already set)."""
        ...


class BaseRetryTracker(ABC):
    """Abstract base class for retry trackers."""

    @abstractmethod
    async def get_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Get current retry count for a message."""

    @abstractmethod
    async def increment_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Increment and return retry count for a message."""

    @abstractmethod
    async def clear_retry_count(self, topic: str, partition: int, offset: int) -> None:
        """Clear retry count after successful processing."""

    @abstractmethod
    async def get_first_failure_time(self, topic: str, partition: int, offset: int) -> datetime | None:
        """Get timestamp of first failure for a message."""

    @abstractmethod
    async def set_first_failure_time(self, topic: str, partition: int, offset: int) -> None:
        """Set first failure timestamp (only if not already set)."""


class RedisRetryTracker(BaseRetryTracker):
    """Redis-backed retry tracking for Kafka message processing.

    Solves: In-memory retry counts lost on service restart, allowing
    messages to retry indefinitely without ever reaching DLQ.

    Key format: {prefix}:{topic}:{partition}:{offset}
    First failure key format: {prefix}:{topic}:{partition}:{offset}:first_failure

    All keys have TTL to prevent indefinite accumulation.
    """

    DEFAULT_TTL_SECONDS = 86400  # 24 hours

    def __init__(
        self,
        redis: RedisClient,
        key_prefix: str = "retry",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """Initialize Redis-backed retry tracker.

        Args:
            redis: Async Redis client instance.
            key_prefix: Prefix for all retry tracking keys.
            ttl_seconds: Time-to-live for retry keys (default 24 hours).

        """
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _make_key(self, topic: str, partition: int, offset: int) -> str:
        """Generate unique key for message tracking."""
        return f"{self._prefix}:{topic}:{partition}:{offset}"

    def _make_first_failure_key(self, topic: str, partition: int, offset: int) -> str:
        """Generate key for first failure timestamp."""
        return f"{self._make_key(topic, partition, offset)}:first_failure"

    async def get_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Get current retry count for a message.

        Args:
            topic: Kafka topic name.
            partition: Kafka partition number.
            offset: Message offset within partition.

        Returns:
            Current retry count, or 0 if not tracked.

        """
        key = self._make_key(topic, partition, offset)
        value = await self._redis.get(key)
        return int(value) if value else 0

    async def increment_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Increment and return retry count, with TTL refresh.

        Uses atomic INCR + EXPIRE in a pipeline to ensure consistency.

        Args:
            topic: Kafka topic name.
            partition: Kafka partition number.
            offset: Message offset within partition.

        Returns:
            New retry count after increment.

        """
        key = self._make_key(topic, partition, offset)

        # Atomic increment with TTL refresh using pipeline
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._ttl)
        results = await pipe.execute()

        new_count = int(results[0])

        logger.debug(
            "Incremented retry count",
            topic=topic,
            partition=partition,
            offset=offset,
            retry_count=new_count,
        )

        return new_count

    async def clear_retry_count(self, topic: str, partition: int, offset: int) -> None:
        """Clear retry count after successful processing.

        Removes both the retry count key and first failure timestamp key.

        Args:
            topic: Kafka topic name.
            partition: Kafka partition number.
            offset: Message offset within partition.

        """
        count_key = self._make_key(topic, partition, offset)
        failure_key = self._make_first_failure_key(topic, partition, offset)

        # Delete both keys atomically
        pipe = self._redis.pipeline()
        pipe.delete(count_key)
        pipe.delete(failure_key)
        await pipe.execute()

        logger.debug(
            "Cleared retry tracking",
            topic=topic,
            partition=partition,
            offset=offset,
        )

    async def get_first_failure_time(self, topic: str, partition: int, offset: int) -> datetime | None:
        """Get timestamp of first failure for a message.

        Args:
            topic: Kafka topic name.
            partition: Kafka partition number.
            offset: Message offset within partition.

        Returns:
            Datetime of first failure, or None if not tracked.

        """
        key = self._make_first_failure_key(topic, partition, offset)
        value = await self._redis.get(key)
        if value is None:
            return None
        decoded_value = value.decode() if isinstance(value, bytes) else str(value)
        return datetime.fromisoformat(decoded_value)

    async def set_first_failure_time(self, topic: str, partition: int, offset: int) -> None:
        """Set first failure timestamp (only if not already set).

        Uses atomic ``SET NX EX`` so the timestamp cannot be left without a TTL.

        Args:
            topic: Kafka topic name.
            partition: Kafka partition number.
            offset: Message offset within partition.

        """
        key = self._make_first_failure_key(topic, partition, offset)
        timestamp = datetime.now(UTC).isoformat()

        was_set = await self._redis.set(key, timestamp, nx=True, ex=self._ttl)
        if was_set:
            logger.debug(
                "Set first failure time",
                topic=topic,
                partition=partition,
                offset=offset,
                timestamp=timestamp,
            )


class InMemoryRetryTracker(BaseRetryTracker):
    """In-memory retry tracker for testing without Redis.

    WARNING: Retry counts are lost on service restart.
    Use RedisRetryTracker in production.
    """

    def __init__(self) -> None:
        """Initialize in-memory retry tracker."""
        self._retry_counts: dict[str, int] = {}
        self._first_failure_times: dict[str, datetime] = {}

    def _make_key(self, topic: str, partition: int, offset: int) -> str:
        """Generate unique key for message tracking."""
        return f"{topic}:{partition}:{offset}"

    async def get_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Get current retry count for a message."""
        key = self._make_key(topic, partition, offset)
        return self._retry_counts.get(key, 0)

    async def increment_retry_count(self, topic: str, partition: int, offset: int) -> int:
        """Increment and return retry count for a message."""
        key = self._make_key(topic, partition, offset)
        current_count = self._retry_counts.get(key, 0)
        new_count = current_count + 1
        self._retry_counts[key] = new_count
        return new_count

    async def clear_retry_count(self, topic: str, partition: int, offset: int) -> None:
        """Clear retry count after successful processing."""
        key = self._make_key(topic, partition, offset)
        self._retry_counts.pop(key, None)
        self._first_failure_times.pop(key, None)

    async def get_first_failure_time(self, topic: str, partition: int, offset: int) -> datetime | None:
        """Get timestamp of first failure for a message."""
        key = self._make_key(topic, partition, offset)
        return self._first_failure_times.get(key)

    async def set_first_failure_time(self, topic: str, partition: int, offset: int) -> None:
        """Set first failure timestamp (only if not already set)."""
        key = self._make_key(topic, partition, offset)
        if key not in self._first_failure_times:
            self._first_failure_times[key] = datetime.now(UTC)

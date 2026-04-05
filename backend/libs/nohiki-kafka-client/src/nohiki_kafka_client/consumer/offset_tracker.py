"""Barrier-based offset tracking for safe Kafka commits with concurrent processing.

With concurrent processing, offsets may complete out of order.  Naively
committing the highest completed offset would skip in-flight offsets,
causing message loss on crash.  This tracker uses a barrier approach:
the committable offset is the highest completed offset below the lowest
pending offset: correctly handling non-contiguous offsets from log
compaction where gaps (e.g., 10, 12, 13) are normal.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from aiokafka import TopicPartition


class PartitionOffsetTracker:
    """Track completed offsets per partition for safe commits.

    Uses a barrier-based approach: the committable offset is the highest
    completed offset below the lowest pending (in-flight) offset.  When
    no offsets are pending, the highest completed offset + 1 is returned.

    This handles non-contiguous offsets from Kafka log compaction correctly
    (e.g., offsets 10, 12, 13 with no 11 ever delivered).

    Thread-safety is provided by an ``asyncio.Lock`` since all callers
    share the same event loop.
    """

    def __init__(self) -> None:
        """Initialize empty offset tracking state."""
        self._pending: dict[TopicPartition, set[int]] = defaultdict(set)
        self._completed: dict[TopicPartition, set[int]] = defaultdict(set)
        self._base_offset: dict[TopicPartition, int] = {}
        self._lock = asyncio.Lock()

    async def register_inflight(self, tp: TopicPartition, offset: int) -> None:
        """Register an offset as in-flight (about to be processed).

        Sets the base offset for the partition on first call, which anchors
        the contiguous scan in ``get_committable_offsets``.

        Args:
            tp: The topic-partition the offset belongs to.
            offset: The offset being processed.

        """
        async with self._lock:
            self._pending[tp].add(offset)
            if tp not in self._base_offset:
                self._base_offset[tp] = offset

    async def mark_completed(self, tp: TopicPartition, offset: int) -> None:
        """Mark an offset as successfully processed.

        Moves the offset from pending to completed.  Called from the
        ``finally`` block of each per-record task so it executes
        regardless of whether the handler succeeded or routed to DLQ.

        Args:
            tp: The topic-partition the offset belongs to.
            offset: The offset that completed processing.

        """
        async with self._lock:
            self._pending[tp].discard(offset)
            self._completed[tp].add(offset)

    async def get_committable_offsets(self) -> dict[TopicPartition, int]:
        """Get the highest safe-to-commit offset per partition.

        Uses a barrier approach: the committable offset is the highest
        completed offset strictly below the lowest pending offset.  If
        no offsets are pending, the highest completed offset + 1 is
        returned.  This correctly handles non-contiguous offsets from
        Kafka log compaction.

        Returns:
            Committable offsets suitable for passing to aiokafka's
            ``commit()``.

        """
        async with self._lock:
            result: dict[TopicPartition, int] = {}
            for tp, completed in self._completed.items():
                if not completed:
                    continue

                pending = self._pending.get(tp)
                if pending:
                    # Barrier: only commit up to the lowest in-flight offset
                    barrier = min(pending)
                    safe = {o for o in completed if o < barrier}
                    if safe:
                        result[tp] = max(safe) + 1
                else:
                    # Nothing pending: safe to commit everything
                    result[tp] = max(completed) + 1

            return result

    async def clear_committed(self, committed: dict[TopicPartition, int]) -> None:
        """Remove offsets below committed thresholds and advance base offsets.

        Called after a successful ``commit()`` to free memory and advance
        the base offset so subsequent contiguous scans start from the
        committed position.

        Args:
            committed: Map of partitions to committed offset values.

        """
        async with self._lock:
            for tp, committed_offset in committed.items():
                if (completed := self._completed.get(tp)) is not None:
                    completed -= {o for o in completed if o < committed_offset}
                if (pending := self._pending.get(tp)) is not None:
                    pending -= {o for o in pending if o < committed_offset}
                self._base_offset[tp] = committed_offset

    async def clear_partitions(self, partitions: set[TopicPartition]) -> None:
        """Clear all tracking state for the given partitions.

        Called during consumer group rebalance when partitions are revoked.
        Discards both in-flight and completed tracking so stale offsets
        from a previous assignment cannot cause incorrect commits.

        Args:
            partitions: Set of topic-partitions being revoked.

        """
        async with self._lock:
            for tp in partitions:
                self._pending.pop(tp, None)
                self._completed.pop(tp, None)
                self._base_offset.pop(tp, None)

    async def has_pending(self) -> bool:
        """Check if any offsets are still in-flight.

        Returns:
            True if any partition has pending (unprocessed) offsets.

        """
        async with self._lock:
            return any(self._pending.values())

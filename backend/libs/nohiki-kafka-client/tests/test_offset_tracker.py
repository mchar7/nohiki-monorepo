"""Unit tests for PartitionOffsetTracker."""

from __future__ import annotations

import asyncio

import pytest
from aiokafka import TopicPartition
from nohiki_kafka_client.consumer.offset_tracker import PartitionOffsetTracker


@pytest.fixture
def tracker() -> PartitionOffsetTracker:
    """Create a fresh PartitionOffsetTracker for each test."""
    return PartitionOffsetTracker()


@pytest.fixture
def tp0() -> TopicPartition:
    """TopicPartition for topic-a, partition 0."""
    return TopicPartition("topic-a", 0)


@pytest.fixture
def tp1() -> TopicPartition:
    """TopicPartition for topic-a, partition 1."""
    return TopicPartition("topic-a", 1)


class TestRegisterInflight:
    """Tests for register_inflight."""

    @pytest.mark.asyncio
    async def test_register_sets_base_offset(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """First registration for a partition sets the base offset."""
        await tracker.register_inflight(tp0, 10)
        assert tracker._base_offset[tp0] == 10

    @pytest.mark.asyncio
    async def test_register_does_not_overwrite_base(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Subsequent registrations do not change the base offset."""
        await tracker.register_inflight(tp0, 10)
        await tracker.register_inflight(tp0, 11)
        assert tracker._base_offset[tp0] == 10

    @pytest.mark.asyncio
    async def test_register_adds_to_pending(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Registered offsets appear in the pending set."""
        await tracker.register_inflight(tp0, 5)
        await tracker.register_inflight(tp0, 6)
        assert tracker._pending[tp0] == {5, 6}


class TestMarkCompleted:
    """Tests for mark_completed."""

    @pytest.mark.asyncio
    async def test_mark_moves_from_pending_to_completed(
        self, tracker: PartitionOffsetTracker, tp0: TopicPartition
    ) -> None:
        """Marking an offset as completed moves it from pending to completed."""
        await tracker.register_inflight(tp0, 10)
        await tracker.mark_completed(tp0, 10)
        assert 10 not in tracker._pending[tp0]
        assert 10 in tracker._completed[tp0]

    @pytest.mark.asyncio
    async def test_mark_completed_without_register(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Marking an offset that was never registered still adds to completed."""
        await tracker.mark_completed(tp0, 42)
        assert 42 in tracker._completed[tp0]


class TestGetCommittableOffsets:
    """Tests for get_committable_offsets."""

    @pytest.mark.asyncio
    async def test_empty_tracker_returns_empty(self, tracker: PartitionOffsetTracker) -> None:
        """Empty tracker returns no committable offsets."""
        result = await tracker.get_committable_offsets()
        assert result == {}

    @pytest.mark.asyncio
    async def test_single_contiguous_offset(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Single completed offset at base returns base+1."""
        await tracker.register_inflight(tp0, 0)
        await tracker.mark_completed(tp0, 0)
        result = await tracker.get_committable_offsets()
        assert result == {tp0: 1}

    @pytest.mark.asyncio
    async def test_full_contiguous_sequence(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """All offsets in a range completed contiguously."""
        for offset in range(10, 15):
            await tracker.register_inflight(tp0, offset)
        for offset in range(10, 15):
            await tracker.mark_completed(tp0, offset)

        result = await tracker.get_committable_offsets()
        assert result == {tp0: 15}

    @pytest.mark.asyncio
    async def test_gap_in_completed_offsets(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Only offsets contiguous from base are committable."""
        for offset in range(10, 15):
            await tracker.register_inflight(tp0, offset)

        await tracker.mark_completed(tp0, 10)
        await tracker.mark_completed(tp0, 11)
        # offset 12 is still pending
        await tracker.mark_completed(tp0, 13)
        await tracker.mark_completed(tp0, 14)

        result = await tracker.get_committable_offsets()
        assert result == {tp0: 12}

    @pytest.mark.asyncio
    async def test_no_contiguous_from_base(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """When the base offset is still pending, nothing is committable."""
        for offset in range(10, 15):
            await tracker.register_inflight(tp0, offset)

        await tracker.mark_completed(tp0, 11)
        await tracker.mark_completed(tp0, 12)

        result = await tracker.get_committable_offsets()
        assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_partitions(
        self, tracker: PartitionOffsetTracker, tp0: TopicPartition, tp1: TopicPartition
    ) -> None:
        """Committable offsets are tracked independently per partition."""
        await tracker.register_inflight(tp0, 0)
        await tracker.register_inflight(tp0, 1)
        await tracker.register_inflight(tp1, 100)
        await tracker.register_inflight(tp1, 101)

        await tracker.mark_completed(tp0, 0)
        # tp0 offset 1 still pending
        await tracker.mark_completed(tp1, 100)
        await tracker.mark_completed(tp1, 101)

        result = await tracker.get_committable_offsets()
        assert result == {tp0: 1, tp1: 102}

    @pytest.mark.asyncio
    async def test_out_of_order_completion(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Offsets completed out of order are handled correctly."""
        for offset in range(5, 10):
            await tracker.register_inflight(tp0, offset)

        await tracker.mark_completed(tp0, 9)
        await tracker.mark_completed(tp0, 7)
        await tracker.mark_completed(tp0, 5)
        await tracker.mark_completed(tp0, 6)
        # offset 8 still pending

        result = await tracker.get_committable_offsets()
        assert result == {tp0: 8}

    @pytest.mark.asyncio
    async def test_non_contiguous_offsets_from_log_compaction(
        self, tracker: PartitionOffsetTracker, tp0: TopicPartition
    ) -> None:
        """Non-contiguous offsets (gap at 11) from log compaction are handled correctly."""
        # Kafka may deliver offsets 10, 12, 13 after log compaction (offset 11 compacted away)
        await tracker.register_inflight(tp0, 10)
        await tracker.register_inflight(tp0, 12)
        await tracker.register_inflight(tp0, 13)

        await tracker.mark_completed(tp0, 10)
        await tracker.mark_completed(tp0, 12)
        await tracker.mark_completed(tp0, 13)

        result = await tracker.get_committable_offsets()
        # All delivered offsets completed, nothing pending: commit past the highest
        assert result == {tp0: 14}

    @pytest.mark.asyncio
    async def test_non_contiguous_with_pending(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Non-contiguous offsets with a pending offset use barrier correctly."""
        await tracker.register_inflight(tp0, 10)
        await tracker.register_inflight(tp0, 12)
        await tracker.register_inflight(tp0, 15)

        await tracker.mark_completed(tp0, 10)
        await tracker.mark_completed(tp0, 15)
        # offset 12 still pending: barrier at 12

        result = await tracker.get_committable_offsets()
        assert result == {tp0: 11}


class TestClearCommitted:
    """Tests for clear_committed."""

    @pytest.mark.asyncio
    async def test_clear_removes_committed_offsets(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Clearing committed offsets removes them from the completed set."""
        for offset in range(10, 15):
            await tracker.register_inflight(tp0, offset)
            await tracker.mark_completed(tp0, offset)

        await tracker.clear_committed({tp0: 13})

        assert tracker._completed[tp0] == {13, 14}
        assert tracker._base_offset[tp0] == 13

    @pytest.mark.asyncio
    async def test_clear_advances_base_offset(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Clearing committed offsets advances the base offset."""
        await tracker.register_inflight(tp0, 0)
        await tracker.mark_completed(tp0, 0)
        await tracker.clear_committed({tp0: 1})

        assert tracker._base_offset[tp0] == 1

    @pytest.mark.asyncio
    async def test_clear_also_removes_old_pending(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Clearing committed offsets also removes old pending offsets."""
        await tracker.register_inflight(tp0, 0)
        await tracker.register_inflight(tp0, 1)
        await tracker.mark_completed(tp0, 0)
        # offset 1 still pending
        await tracker.clear_committed({tp0: 1})

        assert 0 not in tracker._pending[tp0]


class TestClearPartitions:
    """Tests for clear_partitions."""

    @pytest.mark.asyncio
    async def test_clear_removes_all_state(
        self, tracker: PartitionOffsetTracker, tp0: TopicPartition, tp1: TopicPartition
    ) -> None:
        """Clearing a partition removes all tracking state for it."""
        await tracker.register_inflight(tp0, 0)
        await tracker.mark_completed(tp0, 0)
        await tracker.register_inflight(tp1, 100)

        await tracker.clear_partitions({tp0})

        assert tp0 not in tracker._pending
        assert tp0 not in tracker._completed
        assert tp0 not in tracker._base_offset
        # tp1 should be untouched
        assert tp1 in tracker._pending
        assert tp1 in tracker._base_offset

    @pytest.mark.asyncio
    async def test_clear_nonexistent_partition_is_noop(self, tracker: PartitionOffsetTracker) -> None:
        """Clearing a partition with no state does not raise."""
        tp = TopicPartition("no-such-topic", 99)
        await tracker.clear_partitions({tp})


class TestHasPending:
    """Tests for has_pending."""

    @pytest.mark.asyncio
    async def test_empty_tracker_has_no_pending(self, tracker: PartitionOffsetTracker) -> None:
        """Empty tracker has no pending offsets."""
        assert not await tracker.has_pending()

    @pytest.mark.asyncio
    async def test_has_pending_after_register(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Tracker has pending after registering an in-flight offset."""
        await tracker.register_inflight(tp0, 0)
        assert await tracker.has_pending()

    @pytest.mark.asyncio
    async def test_no_pending_after_complete(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Tracker has no pending after all offsets are completed."""
        await tracker.register_inflight(tp0, 0)
        await tracker.mark_completed(tp0, 0)
        assert not await tracker.has_pending()


class TestConcurrentAccess:
    """Tests for thread-safety under concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_register_and_complete(self, tracker: PartitionOffsetTracker, tp0: TopicPartition) -> None:
        """Concurrent register + complete operations produce correct results."""
        count = 100

        async def register_and_complete(offset: int) -> None:
            await tracker.register_inflight(tp0, offset)
            await asyncio.sleep(0)
            await tracker.mark_completed(tp0, offset)

        async with asyncio.TaskGroup() as tg:
            for i in range(count):
                tg.create_task(register_and_complete(i))

        result = await tracker.get_committable_offsets()
        assert result == {tp0: count}
        assert not await tracker.has_pending()

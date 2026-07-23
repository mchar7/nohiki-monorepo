"""Tests for SkillEmbeddingReadinessGate."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from skill_graph_service.core.readiness import SkillEmbeddingReadinessGate


def _make_gate(
    count: int = 0,
    poll_interval: float = 0.0,
    min_point_count: int = 1,
) -> SkillEmbeddingReadinessGate:
    """Build a gate with a mocked Qdrant client."""
    mock_qdrant = AsyncMock()
    mock_qdrant.count_points = AsyncMock(return_value=count)
    return SkillEmbeddingReadinessGate(
        qdrant_client=mock_qdrant,
        collection_name="skills_v1",
        poll_interval_seconds=poll_interval,
        min_point_count=min_point_count,
    )


class TestSkillEmbeddingReadinessGateInit:
    """Tests for SkillEmbeddingReadinessGate initialization."""

    def test_not_ready_on_construction(self) -> None:
        """Gate is not ready immediately after construction."""
        gate = _make_gate()
        assert gate.is_ready is False

    def test_not_failed_on_construction(self) -> None:
        """Gate is not failed immediately after construction."""
        gate = _make_gate()
        assert gate.is_failed is False

    def test_stores_collection_name(self) -> None:
        """Gate stores the collection name."""
        gate = _make_gate()
        assert gate._collection_name == "skills_v1"

    def test_stores_min_point_count(self) -> None:
        """Gate stores the min_point_count threshold."""
        gate = _make_gate(min_point_count=100)
        assert gate._min_point_count == 100


class TestSkillEmbeddingReadinessGateReady:
    """Tests for readiness detection."""

    @pytest.mark.asyncio
    async def test_becomes_ready_when_count_meets_threshold(self) -> None:
        """Gate opens once Qdrant count >= min_point_count."""
        gate = _make_gate(count=5, poll_interval=0.0)
        gate.start()
        assert gate._task is not None
        await gate._task
        assert gate.is_ready is True

    @pytest.mark.asyncio
    async def test_remains_not_ready_when_count_below_threshold(self) -> None:
        """Gate stays closed when count < min_point_count."""
        poll_paused = asyncio.Event()
        resume_polling = asyncio.Event()

        async def pause_after_poll(_: float) -> None:
            poll_paused.set()
            await resume_polling.wait()

        mock_qdrant = AsyncMock()
        mock_qdrant.count_points = AsyncMock(return_value=0)
        gate = SkillEmbeddingReadinessGate(
            qdrant_client=mock_qdrant,
            collection_name="skills_v1",
            poll_interval_seconds=0.05,
            min_point_count=10,
            poll_sleeper=pause_after_poll,
        )
        gate.start()
        await poll_paused.wait()
        await gate.stop()
        assert gate.is_ready is False

    @pytest.mark.asyncio
    async def test_becomes_ready_after_count_rises(self) -> None:
        """Gate opens once count transitions from 0 to threshold mid-poll."""
        counts = [0, 0, 5]
        call_index = 0

        async def rising_count(_: str) -> int:
            nonlocal call_index
            value = counts[min(call_index, len(counts) - 1)]
            call_index += 1
            return value

        mock_qdrant = AsyncMock()
        mock_qdrant.count_points = rising_count
        poll_sleeper = AsyncMock()
        gate = SkillEmbeddingReadinessGate(
            qdrant_client=mock_qdrant,
            collection_name="skills_v1",
            poll_interval_seconds=0.01,
            min_point_count=1,
            poll_sleeper=poll_sleeper,
        )
        gate.start()
        assert gate._task is not None
        await gate._task
        assert gate.is_ready is True

    @pytest.mark.asyncio
    async def test_min_point_count_one_by_default_in_helper(self) -> None:
        """Gate opens with min_point_count=1 when Qdrant has 1 point."""
        gate = _make_gate(count=1, poll_interval=0.0)
        gate.start()
        assert gate._task is not None
        await gate._task
        assert gate.is_ready is True


class TestSkillEmbeddingReadinessGateErrorHandling:
    """Tests for error handling in the polling loop."""

    @pytest.mark.asyncio
    async def test_poll_survives_qdrant_exception(self) -> None:
        """Poll loop continues after a Qdrant exception and eventually opens."""
        call_count = 0

        async def flaky_count(_: str) -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                msg = "Qdrant connection refused"
                raise OSError(msg)
            return 10

        mock_qdrant = AsyncMock()
        mock_qdrant.count_points = flaky_count
        gate = SkillEmbeddingReadinessGate(
            qdrant_client=mock_qdrant,
            collection_name="skills_v1",
            poll_interval_seconds=0.0,
            min_point_count=1,
            poll_sleeper=AsyncMock(),
        )
        gate.start()
        assert gate._task is not None
        await gate._task
        assert gate.is_ready is True

    @pytest.mark.asyncio
    async def test_is_failed_remains_false_during_normal_polling(self) -> None:
        """is_failed stays False even when poll raises intermittent exceptions."""
        poll_paused = asyncio.Event()
        resume_polling = asyncio.Event()

        async def pause_after_poll(_: float) -> None:
            poll_paused.set()
            await resume_polling.wait()

        mock_qdrant = AsyncMock()
        mock_qdrant.count_points = AsyncMock(side_effect=OSError("transient"))
        gate = SkillEmbeddingReadinessGate(
            qdrant_client=mock_qdrant,
            collection_name="skills_v1",
            poll_interval_seconds=0.01,
            min_point_count=1,
            poll_sleeper=pause_after_poll,
        )
        gate.start()
        await poll_paused.wait()
        await gate.stop()
        assert gate.is_failed is False


class TestSkillEmbeddingReadinessGateLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_never_started(self) -> None:
        """stop() does not raise even if start() was never called."""
        gate = _make_gate()
        await gate.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_background_task(self) -> None:
        """stop() cancels the background polling task cleanly."""
        mock_qdrant = AsyncMock()
        mock_qdrant.count_points = AsyncMock(return_value=0)
        gate = SkillEmbeddingReadinessGate(
            qdrant_client=mock_qdrant,
            collection_name="skills_v1",
            poll_interval_seconds=100.0,
            min_point_count=1,
        )
        gate.start()
        assert gate._task is not None
        assert not gate._task.done()
        await gate.stop()
        assert gate._task.done()

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_already_ready(self) -> None:
        """stop() can be safely called after the gate is already open."""
        gate = _make_gate(count=10, poll_interval=0.0)
        gate.start()
        assert gate._task is not None
        await gate._task
        assert gate.is_ready is True
        await gate.stop()

    @pytest.mark.asyncio
    async def test_start_creates_asyncio_task(self) -> None:
        """start() creates an asyncio Task named skill-readiness-gate."""
        gate = _make_gate(count=0, poll_interval=100.0)
        gate.start()
        assert gate._task is not None
        assert isinstance(gate._task, asyncio.Task)
        await gate.stop()


class TestReadinessGateProtocolCompliance:
    """Verify SkillEmbeddingReadinessGate satisfies ReadinessGateProtocol."""

    def test_satisfies_readiness_gate_protocol(self) -> None:
        """SkillEmbeddingReadinessGate is a structural subtype of ReadinessGateProtocol."""
        from nohiki_fastapi_utils.health_router import ReadinessGateProtocol

        gate = _make_gate()
        assert isinstance(gate, ReadinessGateProtocol)

    def test_is_ready_is_bool(self) -> None:
        """is_ready returns a plain bool."""
        gate = _make_gate()
        assert type(gate.is_ready) is bool

    def test_is_failed_is_bool(self) -> None:
        """is_failed returns a plain bool."""
        gate = _make_gate()
        assert type(gate.is_failed) is bool

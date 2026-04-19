"""Tests for ReadinessGate lifecycle management."""

from __future__ import annotations

from ml_compute_service.core.readiness import ReadinessGate, ReadinessState


class TestReadinessGateInit:
    """Tests for ReadinessGate initialization."""

    def test_starts_in_loading_state(self) -> None:
        """New gate starts in LOADING state."""
        gate = ReadinessGate()
        assert gate.state == ReadinessState.LOADING

    def test_is_ready_false_when_loading(self) -> None:
        """is_ready is False in LOADING state."""
        gate = ReadinessGate()
        assert gate.is_ready is False

    def test_is_failed_false_when_loading(self) -> None:
        """is_failed is False in LOADING state."""
        gate = ReadinessGate()
        assert gate.is_failed is False


class TestReadinessGateTransitions:
    """Tests for ReadinessGate state transitions."""

    def test_mark_ready_transitions_to_ready(self) -> None:
        """mark_ready sets state to READY."""
        gate = ReadinessGate()
        gate.mark_ready()
        assert gate.state == ReadinessState.READY
        assert gate.is_ready is True
        assert gate.is_failed is False

    def test_mark_failed_transitions_to_failed(self) -> None:
        """mark_failed sets state to FAILED."""
        gate = ReadinessGate()
        gate.mark_failed()
        assert gate.state == ReadinessState.FAILED
        assert gate.is_failed is True
        assert gate.is_ready is False

    def test_reset_returns_to_loading(self) -> None:
        """Reset returns gate to LOADING from any state."""
        gate = ReadinessGate()
        gate.mark_ready()
        assert gate.is_ready is True

        gate.reset()
        assert gate.state == ReadinessState.LOADING
        assert gate.is_ready is False

    def test_reset_from_failed(self) -> None:
        """Reset returns gate to LOADING from FAILED state."""
        gate = ReadinessGate()
        gate.mark_failed()
        gate.reset()
        assert gate.state == ReadinessState.LOADING

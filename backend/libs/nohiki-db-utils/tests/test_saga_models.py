"""Tests for nohiki_db_utils.saga.models module.

Tests use a lightweight plain Python class that inherits from StateMachineMixin
directly: no SQLAlchemy ORM session needed for unit tests of the state machine
and is_complete logic.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from nohiki_db_utils.saga.models import SagaBaseMixin, SagaStatus
from nohiki_db_utils.state_machine import InvalidTransitionError, StateMachineMixin


class PlainSaga(StateMachineMixin):
    """Lightweight non-ORM stand-in for testing SagaBaseMixin behaviour.

    Mirrors exactly the fields and transitions defined in SagaBaseMixin without
    needing SQLAlchemy instrumentation.
    """

    __status_field__: ClassVar[str] = "status"
    __transitions__: ClassVar[dict[str, frozenset[str]]] = {
        "PENDING": frozenset({"COMPLETED", "FAILED", "EXPIRED", "CANCELLED"}),
        "COMPLETED": frozenset(),
        "FAILED": frozenset(),
        "EXPIRED": frozenset(),
        "CANCELLED": frozenset(),
    }

    def __init__(
        self,
        *,
        status: SagaStatus = SagaStatus.PENDING,
        expected_callbacks: int = 2,
        received_callbacks: int = 0,
    ) -> None:
        """Initialise with saga state."""
        self.status = status
        self.expected_callbacks = expected_callbacks
        self.received_callbacks = received_callbacks

    @property
    def is_complete(self) -> bool:
        """Mirror SagaBaseMixin.is_complete."""
        return self.received_callbacks >= self.expected_callbacks


class TestSagaStatus:
    """Tests for SagaStatus enum."""

    def test_values(self) -> None:
        """SagaStatus has expected values."""
        assert SagaStatus.PENDING == "PENDING"
        assert SagaStatus.COMPLETED == "COMPLETED"
        assert SagaStatus.FAILED == "FAILED"
        assert SagaStatus.EXPIRED == "EXPIRED"
        assert SagaStatus.CANCELLED == "CANCELLED"

    def test_is_str_enum(self) -> None:
        """SagaStatus values are strings."""
        for status in SagaStatus:
            assert isinstance(status, str)

    def test_all_five_states_defined(self) -> None:
        """Exactly five saga states exist."""
        assert len(SagaStatus) == 5


class TestSagaIsComplete:
    """Tests for the is_complete sentinel on SagaBaseMixin."""

    def test_false_when_no_callbacks_received(self) -> None:
        """is_complete is False when received < expected."""
        saga = PlainSaga(expected_callbacks=2, received_callbacks=0)
        assert saga.is_complete is False

    def test_false_when_partially_received(self) -> None:
        """is_complete is False when only some callbacks arrived."""
        saga = PlainSaga(expected_callbacks=2, received_callbacks=1)
        assert saga.is_complete is False

    def test_true_when_all_received(self) -> None:
        """is_complete is True when received == expected."""
        saga = PlainSaga(expected_callbacks=2, received_callbacks=2)
        assert saga.is_complete is True

    def test_true_when_over_received(self) -> None:
        """is_complete is True when received > expected (idempotent callbacks)."""
        saga = PlainSaga(expected_callbacks=2, received_callbacks=3)
        assert saga.is_complete is True

    def test_single_callback_saga(self) -> None:
        """Single-callback saga completes on first callback."""
        saga = PlainSaga(expected_callbacks=1, received_callbacks=1)
        assert saga.is_complete is True


class TestSagaTransitions:
    """Tests for SagaBaseMixin state transitions."""

    def test_pending_to_completed(self) -> None:
        """PENDING → COMPLETED is valid."""
        saga = PlainSaga(status=SagaStatus.PENDING)
        saga.transition_to(SagaStatus.COMPLETED)
        assert saga.status == SagaStatus.COMPLETED

    def test_pending_to_failed(self) -> None:
        """PENDING → FAILED is valid."""
        saga = PlainSaga(status=SagaStatus.PENDING)
        saga.transition_to(SagaStatus.FAILED)
        assert saga.status == SagaStatus.FAILED

    def test_pending_to_expired(self) -> None:
        """PENDING → EXPIRED is valid."""
        saga = PlainSaga(status=SagaStatus.PENDING)
        saga.transition_to(SagaStatus.EXPIRED)
        assert saga.status == SagaStatus.EXPIRED

    def test_pending_to_cancelled(self) -> None:
        """PENDING → CANCELLED is valid."""
        saga = PlainSaga(status=SagaStatus.PENDING)
        saga.transition_to(SagaStatus.CANCELLED)
        assert saga.status == SagaStatus.CANCELLED

    def test_completed_is_terminal(self) -> None:
        """COMPLETED is terminal: no outgoing transitions."""
        saga = PlainSaga(status=SagaStatus.COMPLETED)
        assert saga.is_terminal is True
        assert saga.allowed_transitions == frozenset()

    def test_failed_is_terminal(self) -> None:
        """FAILED is terminal."""
        saga = PlainSaga(status=SagaStatus.FAILED)
        assert saga.is_terminal is True

    def test_expired_is_terminal(self) -> None:
        """EXPIRED is terminal."""
        saga = PlainSaga(status=SagaStatus.EXPIRED)
        assert saga.is_terminal is True

    def test_cancelled_is_terminal(self) -> None:
        """CANCELLED is terminal."""
        saga = PlainSaga(status=SagaStatus.CANCELLED)
        assert saga.is_terminal is True

    def test_pending_is_not_terminal(self) -> None:
        """PENDING is not terminal."""
        saga = PlainSaga(status=SagaStatus.PENDING)
        assert saga.is_terminal is False

    def test_invalid_transition_from_terminal_raises(self) -> None:
        """Invalid transition from terminal state raises InvalidTransitionError."""
        saga = PlainSaga(status=SagaStatus.COMPLETED)
        with pytest.raises(InvalidTransitionError):
            saga.transition_to(SagaStatus.PENDING)

    def test_invalid_transition_raises_correct_attributes(self) -> None:
        """InvalidTransitionError carries structured metadata."""
        saga = PlainSaga(status=SagaStatus.FAILED)
        with pytest.raises(InvalidTransitionError) as exc_info:
            saga.transition_to(SagaStatus.PENDING)
        err = exc_info.value
        assert err.current_state == "FAILED"
        assert err.target_state == "PENDING"

    def test_allowed_transitions_from_pending(self) -> None:
        """PENDING has exactly the four valid terminal targets."""
        saga = PlainSaga(status=SagaStatus.PENDING)
        assert saga.allowed_transitions == frozenset({"COMPLETED", "FAILED", "EXPIRED", "CANCELLED"})


class TestSagaBaseMixinMetadata:
    """Tests for SagaBaseMixin class-level metadata."""

    def test_status_field_name(self) -> None:
        """__status_field__ is 'status'."""
        assert SagaBaseMixin.__status_field__ == "status"

    def test_abstract_flag(self) -> None:
        """SagaBaseMixin declares itself abstract."""
        assert SagaBaseMixin.__abstract__ is True

    def test_transitions_defined(self) -> None:
        """All five states appear in __transitions__ keys."""
        transitions = SagaBaseMixin.__transitions__
        assert "PENDING" in transitions
        assert "COMPLETED" in transitions
        assert "FAILED" in transitions
        assert "EXPIRED" in transitions
        assert "CANCELLED" in transitions

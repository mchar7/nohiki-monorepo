"""Tests for StateMachineMixin and InvalidTransitionError."""

from __future__ import annotations

import enum

import pytest
from nohiki_db_utils import InvalidTransitionError, StateMachineMixin


class Status(enum.Enum):
    """Test enum for state machine tests."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class FakeEntity(StateMachineMixin):
    """Minimal entity for testing state machine behavior."""

    __transitions__ = {
        "PENDING": frozenset({"IN_PROGRESS"}),
        "IN_PROGRESS": frozenset({"COMPLETED", "FAILED"}),
        "FAILED": frozenset({"PENDING"}),
        "COMPLETED": frozenset(),
    }

    def __init__(self, status: Status) -> None:
        self.status = status


class TestStateMachineMixin:
    """Tests for StateMachineMixin.transition_to()."""

    def test_valid_transition_pending_to_in_progress(self) -> None:
        """Valid transition from PENDING to IN_PROGRESS succeeds."""
        entity = FakeEntity(Status.PENDING)
        result = entity.transition_to(Status.IN_PROGRESS)

        assert entity.status is Status.IN_PROGRESS
        assert result is entity

    def test_valid_transition_in_progress_to_completed(self) -> None:
        """Valid transition from IN_PROGRESS to COMPLETED succeeds."""
        entity = FakeEntity(Status.IN_PROGRESS)
        entity.transition_to(Status.COMPLETED)

        assert entity.status is Status.COMPLETED

    def test_valid_transition_in_progress_to_failed(self) -> None:
        """Valid transition from IN_PROGRESS to FAILED succeeds."""
        entity = FakeEntity(Status.IN_PROGRESS)
        entity.transition_to(Status.FAILED)

        assert entity.status is Status.FAILED

    def test_valid_transition_failed_to_pending_retry(self) -> None:
        """Valid retry transition from FAILED back to PENDING succeeds."""
        entity = FakeEntity(Status.FAILED)
        entity.transition_to(Status.PENDING)

        assert entity.status is Status.PENDING

    def test_invalid_transition_raises(self) -> None:
        """Invalid transition from PENDING to COMPLETED raises."""
        entity = FakeEntity(Status.PENDING)

        with pytest.raises(InvalidTransitionError, match=r"PENDING.*COMPLETED"):
            entity.transition_to(Status.COMPLETED)

        assert entity.status is Status.PENDING

    def test_invalid_transition_from_terminal_state(self) -> None:
        """Terminal state COMPLETED rejects all transitions."""
        entity = FakeEntity(Status.COMPLETED)

        with pytest.raises(InvalidTransitionError, match="terminal state"):
            entity.transition_to(Status.PENDING)

    def test_invalid_transition_error_attributes(self) -> None:
        """InvalidTransitionError carries structured error data."""
        entity = FakeEntity(Status.PENDING)

        with pytest.raises(InvalidTransitionError) as exc_info:
            entity.transition_to(Status.FAILED)

        err = exc_info.value
        assert err.entity_type == "FakeEntity"
        assert err.current_state == "PENDING"
        assert err.target_state == "FAILED"
        assert err.allowed_targets == frozenset({"IN_PROGRESS"})

    def test_fluent_chaining(self) -> None:
        """transition_to returns self for fluent chaining."""
        entity = FakeEntity(Status.PENDING)
        result = entity.transition_to(Status.IN_PROGRESS).transition_to(Status.COMPLETED)

        assert result is entity
        assert entity.status is Status.COMPLETED

    def test_full_lifecycle(self) -> None:
        """Walk through a complete lifecycle: PENDING → IN_PROGRESS → COMPLETED."""
        entity = FakeEntity(Status.PENDING)
        entity.transition_to(Status.IN_PROGRESS)
        entity.transition_to(Status.COMPLETED)

        assert entity.status is Status.COMPLETED

    def test_retry_lifecycle(self) -> None:
        """Walk through a retry lifecycle: PENDING → IN_PROGRESS → FAILED → PENDING."""
        entity = FakeEntity(Status.PENDING)
        entity.transition_to(Status.IN_PROGRESS)
        entity.transition_to(Status.FAILED)
        entity.transition_to(Status.PENDING)

        assert entity.status is Status.PENDING


class TestIsTerminal:
    """Tests for StateMachineMixin.is_terminal property."""

    def test_terminal_state(self) -> None:
        """COMPLETED is a terminal state (empty transition set)."""
        entity = FakeEntity(Status.COMPLETED)
        assert entity.is_terminal is True

    def test_non_terminal_state(self) -> None:
        """PENDING is not terminal (has outgoing transitions)."""
        entity = FakeEntity(Status.PENDING)
        assert entity.is_terminal is False

    def test_failed_is_not_terminal(self) -> None:
        """FAILED is not terminal (can retry to PENDING)."""
        entity = FakeEntity(Status.FAILED)
        assert entity.is_terminal is False


class TestAllowedTransitions:
    """Tests for StateMachineMixin.allowed_transitions property."""

    def test_pending_allowed(self) -> None:
        """PENDING can only transition to IN_PROGRESS."""
        entity = FakeEntity(Status.PENDING)
        assert entity.allowed_transitions == frozenset({"IN_PROGRESS"})

    def test_in_progress_allowed(self) -> None:
        """IN_PROGRESS can transition to COMPLETED or FAILED."""
        entity = FakeEntity(Status.IN_PROGRESS)
        assert entity.allowed_transitions == frozenset({"COMPLETED", "FAILED"})

    def test_completed_allowed_empty(self) -> None:
        """COMPLETED has no allowed transitions."""
        entity = FakeEntity(Status.COMPLETED)
        assert entity.allowed_transitions == frozenset()


class TestStringStatus:
    """Tests for StateMachineMixin with plain string status values."""

    class StringEntity(StateMachineMixin):
        """Test entity using plain string status values."""

        __transitions__ = {
            "active": frozenset({"archived"}),
            "archived": frozenset(),
        }

        def __init__(self, status: str) -> None:
            self.status = status

    def test_string_valid_transition(self) -> None:
        """String-based status transitions work correctly."""
        entity = self.StringEntity("active")
        entity.transition_to("archived")
        assert entity.status == "archived"

    def test_string_invalid_transition(self) -> None:
        """String-based invalid transitions raise correctly."""
        entity = self.StringEntity("archived")
        with pytest.raises(InvalidTransitionError, match=r"archived.*active"):
            entity.transition_to("active")


class TestCustomStatusField:
    """Tests for StateMachineMixin with custom __status_field__."""

    class CustomFieldEntity(StateMachineMixin):
        """Test entity using a custom status field name."""

        __status_field__ = "lifecycle_state"
        __transitions__ = {
            "DRAFT": frozenset({"PUBLISHED"}),
            "PUBLISHED": frozenset({"ARCHIVED"}),
            "ARCHIVED": frozenset(),
        }

        def __init__(self, lifecycle_state: str) -> None:
            self.lifecycle_state = lifecycle_state

    def test_custom_field_transition(self) -> None:
        """Transitions work with a custom status field name."""
        entity = self.CustomFieldEntity("DRAFT")
        entity.transition_to("PUBLISHED")
        assert entity.lifecycle_state == "PUBLISHED"

    def test_custom_field_is_terminal(self) -> None:
        """is_terminal reads from custom field."""
        entity = self.CustomFieldEntity("ARCHIVED")
        assert entity.is_terminal is True

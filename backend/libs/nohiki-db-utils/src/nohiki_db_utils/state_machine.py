"""Explicit state machine enforcement for entity lifecycle management.

Provides a mixin that validates state transitions against a declared
transition map, preventing invalid lifecycle changes at the application
layer before they reach the database.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar, Self


class InvalidTransitionError(Exception):
    """Raised when an entity attempts a state transition not in its transition map.

    Attributes:
        entity_type: Name of the entity class.
        current_state: The state the entity is currently in.
        target_state: The state the entity attempted to transition to.
        allowed_targets: The set of states reachable from current_state.

    """

    def __init__(
        self,
        *,
        entity_type: str,
        current_state: str,
        target_state: str,
        allowed_targets: frozenset[str],
    ) -> None:
        """Initialize with transition context for structured error reporting."""
        self.entity_type = entity_type
        self.current_state = current_state
        self.target_state = target_state
        self.allowed_targets = allowed_targets
        super().__init__(
            f"{entity_type}: invalid transition "
            f"{current_state!r} → {target_state!r} "
            f"(allowed: {sorted(allowed_targets) if allowed_targets else 'terminal state'})"
        )


def _enum_name(value: Enum | str) -> str:
    """Extract the canonical string name from an enum member or plain string."""
    if isinstance(value, Enum):
        return value.name
    return str(value)


class StateMachineMixin:
    """Enforces valid state transitions on a status column.

    Subclasses declare ``__transitions__`` mapping each state name to
    the ``frozenset`` of valid next-state names, and ``__status_field__``
    identifying which column holds the current state.

    Transition keys and values use **enum member names** (e.g. ``"ACTIVE"``,
    not ``"LISTING_STATUS_ACTIVE"``). This works with both protobuf enums
    (betterproto2) and Python stdlib ``enum.Enum``.

    Example::

        class Listing(BaseEntity, StateMachineMixin, Base):
            __status_field__ = "status"
            __transitions__ = {
                "ACTIVE": frozenset({"STALE", "EXPIRED"}),
                "STALE": frozenset({"ACTIVE", "EXPIRED"}),
                "EXPIRED": frozenset(),
            }

    """

    __transitions__: ClassVar[dict[str, frozenset[str]]] = {}
    __status_field__: ClassVar[str] = "status"

    def transition_to(self, target: Enum | str) -> Self:
        """Validate and apply a state transition.

        Args:
            target: The desired new state (enum member or string name).

        Returns:
            ``self`` for fluent chaining.

        Raises:
            InvalidTransitionError: If the transition is not declared in
                ``__transitions__``.

        """
        current_raw = getattr(self, self.__status_field__)
        current_name = _enum_name(current_raw)
        target_name = _enum_name(target)

        allowed = self.__transitions__.get(current_name, frozenset())

        if target_name not in allowed:
            raise InvalidTransitionError(
                entity_type=type(self).__name__,
                current_state=current_name,
                target_state=target_name,
                allowed_targets=allowed,
            )

        setattr(self, self.__status_field__, target)
        return self

    @property
    def is_terminal(self) -> bool:
        """Check whether the current state has no outgoing transitions."""
        current_name = _enum_name(getattr(self, self.__status_field__))
        return not self.__transitions__.get(current_name, frozenset())

    @property
    def allowed_transitions(self) -> frozenset[str]:
        """Return the set of state names reachable from the current state."""
        current_name = _enum_name(getattr(self, self.__status_field__))
        return self.__transitions__.get(current_name, frozenset())

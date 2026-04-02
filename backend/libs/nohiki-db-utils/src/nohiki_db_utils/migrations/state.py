"""Migration state management for health check integration.

Provides global state tracking for migration progress and status.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

type MigrationStatus = Literal["not_started", "in_progress", "completed", "failed"]


class MigrationError(Exception):
    """Migration failed - prevents application startup."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        super().__init__(message)
        self.message = message


@dataclass(slots=True)
class MigrationState:
    """Global migration state for health check integration."""

    status: MigrationStatus = "not_started"
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    current_revision: str | None = None
    target_revision: str | None = None

    def is_healthy(self) -> bool:
        """Return True only if migrations completed successfully."""
        return self.status == "completed"

    def to_dict(self) -> dict[str, str | float | bool | None]:
        """Convert to dictionary for health check response."""
        return {
            "status": self.status,
            "healthy": self.is_healthy(),
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "current_revision": self.current_revision,
            "target_revision": self.target_revision,
        }


_migration_state = MigrationState()


def get_migration_state() -> MigrationState:
    """Get the global migration state for health checks."""
    return _migration_state


def skip_migrations() -> None:
    """Mark migrations as not required for services that don't use a database."""
    _migration_state.status = "completed"
    _migration_state.completed_at = time.time()


def set_migration_status(
    status: MigrationStatus,
    *,
    error: str | None = None,
    current_revision: str | None = None,
    target_revision: str | None = None,
) -> None:
    """Update global migration state (mutates singleton, no reassignment)."""
    _migration_state.status = status
    if error is not None:
        _migration_state.error = error
    if current_revision is not None:
        _migration_state.current_revision = current_revision
    if target_revision is not None:
        _migration_state.target_revision = target_revision
    if status == "in_progress" and _migration_state.started_at is None:
        _migration_state.started_at = time.time()
    if status in ("completed", "failed"):
        _migration_state.completed_at = time.time()

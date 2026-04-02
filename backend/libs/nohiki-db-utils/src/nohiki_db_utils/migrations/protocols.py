"""Protocol definitions for database configuration and settings.

Defines the contracts that service settings must implement to use the migration system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DatabaseConfig(Protocol):
    """Protocol for database configuration section."""

    @property
    def connection_string(self) -> str:
        """Database connection string."""
        ...

    @property
    def migrate_on_startup(self) -> bool:
        """Whether to run migrations on startup."""
        ...

    @property
    def migration_timeout_seconds(self) -> int:
        """Timeout for migration execution."""
        ...

    def get_connect_args(self) -> dict[str, Any]:
        """Get connect_args for SQLAlchemy async engine."""
        ...


@runtime_checkable
class DatabaseSettingsProvider(Protocol):
    """Protocol for settings that can initialize database."""

    @property
    def service_name(self) -> str:
        """Service name for lock coordination."""
        ...

    @property
    def database(self) -> DatabaseConfig | None:
        """Database configuration section."""
        ...


@dataclass(frozen=True, slots=True)
class LockContext:
    """Context for lock handling operations."""

    service_name: str
    pod_id: str
    database_url: str
    alembic_config_path: str

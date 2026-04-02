"""Distributed migration coordination using PostgreSQL advisory locks.

Public API for database migration management in multi-pod deployments.
"""

from .cli import migrate_cli
from .coordinator import initialize_database, run_migrations_with_coordination
from .protocols import DatabaseConfig, DatabaseSettingsProvider, LockContext
from .state import (
    MigrationError,
    MigrationState,
    get_migration_state,
    set_migration_status,
    skip_migrations,
)

__all__ = [
    "DatabaseConfig",
    "DatabaseSettingsProvider",
    "LockContext",
    "MigrationError",
    "MigrationState",
    "get_migration_state",
    "initialize_database",
    "migrate_cli",
    "run_migrations_with_coordination",
    "set_migration_status",
    "skip_migrations",
]

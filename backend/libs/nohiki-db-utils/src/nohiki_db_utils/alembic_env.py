"""Alembic environment utilities for consistent migration configuration.

Provides centralized utilities for alembic env.py files to avoid DRY violations
across services. Handles database URL resolution, driver conversion, and
standard migration configuration.

Usage in env.py:
    from nohiki_db_utils.alembic_env import (
        get_sync_database_url,
        configure_migration_context,
        run_migrations_offline,
        run_migrations_online,
    )
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import Connection

if TYPE_CHECKING:
    from alembic.config import Config
    from sqlalchemy import MetaData

_PG_ASYNCPG_DRIVER = "+asyncpg"
_PG_PSYCOPG_DRIVER = "+psycopg"
_PG_SCHEME = "postgresql://"
_PG_PSYCOPG_SCHEME = "postgresql+psycopg://"

_DATABASE_URL_ENV_VAR = "DATABASE_URL"


def _normalize_to_sync_url(url: str) -> str:
    """Convert any PostgreSQL URL to sync psycopg driver.

    Handles:
    - postgresql+asyncpg:// -> postgresql+psycopg://
    - postgresql:// -> postgresql+psycopg://
    - Already psycopg URLs are returned unchanged

    Also strips sslmode from query params since psycopg handles it differently
    than asyncpg (psycopg accepts sslmode directly, no conversion needed).
    """
    # Convert asyncpg to psycopg
    if _PG_ASYNCPG_DRIVER in url:
        url = url.replace(_PG_ASYNCPG_DRIVER, _PG_PSYCOPG_DRIVER)
    # Ensure we have explicit psycopg driver
    elif _PG_PSYCOPG_DRIVER not in url and url.startswith(_PG_SCHEME):
        url = url.replace(_PG_SCHEME, _PG_PSYCOPG_SCHEME)

    return url


def get_sync_database_url(alembic_config: Config) -> str:
    """Get database URL for sync migrations.

    Resolution order:
    1. DATABASE_URL environment variable (preferred for runtime)
    2. alembic.ini sqlalchemy.url (fallback for local development)

    The URL is automatically converted to use the psycopg sync driver.

    Args:
        alembic_config: Alembic Config object from context.config

    Returns:
        Database URL with sync driver

    Raises:
        ValueError: If no valid database URL can be resolved
    """
    # Try environment variable first
    url = os.environ.get(_DATABASE_URL_ENV_VAR)

    # Fall back to alembic.ini config
    if not url:
        url = alembic_config.get_main_option("sqlalchemy.url")

    if not url:
        msg = (
            f"No database URL found. Set {_DATABASE_URL_ENV_VAR} environment variable "
            "or configure sqlalchemy.url in alembic.ini"
        )
        raise ValueError(msg)

    # Validate it's a PostgreSQL URL
    if not url.startswith("postgresql"):
        msg = f"Expected PostgreSQL URL, got: {url[:20]}..."
        raise ValueError(msg)

    return _normalize_to_sync_url(url)


def create_schema_if_not_exists(connection: Connection, schema_name: str) -> None:
    """Create schema if it doesn't exist (idempotent)."""
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
    connection.commit()


def configure_offline_context(
    url: str,
    target_metadata: MetaData,
    *,
    version_table_schema: str | None = None,
    include_schemas: bool = True,
) -> None:
    """Configure alembic context for offline (SQL script) mode.

    Args:
        url: Database URL (sync driver)
        target_metadata: SQLAlchemy MetaData for the models
        version_table_schema: Schema for alembic_version table (optional)
        include_schemas: Whether to include schema prefixes in output
    """
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=version_table_schema,
        include_schemas=include_schemas,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online_migrations(
    url: str,
    target_metadata: MetaData,
    *,
    version_table_schema: str | None = None,
    include_schemas: bool = True,
    create_schema: bool = True,
) -> None:
    """Run migrations in online mode with a real database connection.

    Creates the version_table_schema if specified and create_schema=True.

    Args:
        url: Database URL (sync driver)
        target_metadata: SQLAlchemy MetaData for the models
        version_table_schema: Schema for alembic_version table and to create
        include_schemas: Whether to include schema prefixes
        create_schema: Whether to create the schema if it doesn't exist
    """
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Create schema if requested
        if version_table_schema and create_schema:
            create_schema_if_not_exists(connection, version_table_schema)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=version_table_schema,
            include_schemas=include_schemas,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()

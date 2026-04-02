"""CLI entrypoint for database migrations.

Used by Kubernetes init containers to run migrations before the main application starts.
Executes migrations with distributed coordination via PostgreSQL advisory locks.
"""

from __future__ import annotations

import asyncio
import os
import sys

from nohiki_observability import get_logger

from .coordinator import run_migrations_with_coordination
from .state import MigrationError

logger = get_logger(__name__)


async def _run_migration() -> None:
    """Execute database migration with coordination."""
    service_name = os.environ.get("SERVICE_NAME")
    database_url = os.environ.get("DATABASE_URL")
    timeout_seconds = int(os.environ.get("MIGRATION_TIMEOUT_SECONDS", "120"))
    alembic_config_path = os.environ.get("ALEMBIC_CONFIG_PATH", "alembic.ini")

    if not service_name:
        msg = "SERVICE_NAME environment variable is required"
        raise MigrationError(msg)

    if not database_url:
        msg = "DATABASE_URL environment variable is required"
        raise MigrationError(msg)

    logger.info(
        "Starting database migration via CLI",
        service=service_name,
        alembic_config=alembic_config_path,
        timeout_seconds=timeout_seconds,
    )

    await run_migrations_with_coordination(
        service_name=service_name,
        database_url=database_url,
        timeout_seconds=timeout_seconds,
        alembic_config_path=alembic_config_path,
    )

    logger.info("Database migration completed", service=service_name)


def migrate_cli() -> None:
    """CLI entrypoint for running database migrations.

    Intended for use in Kubernetes init containers. Reads configuration from
    environment variables:

    Required:
        SERVICE_NAME: Name of the service (used for lock ID generation)
        DATABASE_URL: Complete PostgreSQL connection string (postgresql+asyncpg://...)

    Optional:
        ALEMBIC_CONFIG_PATH: Path to alembic.ini (default: "alembic.ini")
        MIGRATION_TIMEOUT_SECONDS: Lock acquisition timeout (default: 120)

    Exit codes:
        0: Success
        1: Migration failed

    """
    try:
        asyncio.run(_run_migration())
    except MigrationError as err:
        logger.exception("Migration failed", error=str(err))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Migration interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    migrate_cli()

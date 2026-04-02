"""Alembic migration execution with timeout handling.

Provides controlled execution of Alembic upgrade commands with
error handling and time limits.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path

import alembic.command as alembic_command
from alembic.config import Config
from alembic.util.exc import CommandError
from nohiki_observability import get_logger
from sqlalchemy.exc import SQLAlchemyError

from .state import MigrationError, set_migration_status
from .url_utils import to_sync_url

logger = get_logger(__name__)


async def _drain_migration(migration: asyncio.Future[None]) -> None:
    """Wait for a thread-backed migration despite repeated task cancellation."""
    while True:
        try:
            with suppress(Exception):
                await asyncio.shield(migration)
        except asyncio.CancelledError:
            if migration.done():
                return
            if (current_task := asyncio.current_task()) is None:
                raise
            current_task.uncancel()
        else:
            return


async def execute_migrations(service_name: str, db_url: str, max_seconds: int, config_path: str) -> None:
    """Run Alembic upgrade in executor with time limit."""
    logger.info(
        "Starting migration execution",
        service=service_name,
        max_duration_seconds=max_seconds,
    )

    migration = asyncio.get_event_loop().run_in_executor(None, run_alembic_upgrade, config_path, db_url)
    awaited_migration = asyncio.shield(migration) if isinstance(migration, asyncio.Future) else migration
    try:
        await asyncio.wait_for(awaited_migration, timeout=max_seconds)
        logger.info(
            "Alembic migration execution completed",
            service=service_name,
        )

    except asyncio.CancelledError:
        # Cancellation must not let the advisory lock escape a live migration.
        if (current_task := asyncio.current_task()) is not None:
            current_task.uncancel()
        if isinstance(migration, asyncio.Future):
            await _drain_migration(migration)
        raise
    except TimeoutError as err:
        # A thread cannot be cancelled safely. Keep the coordinator's advisory
        # lock held until Alembic actually exits, then report the deadline miss.
        if isinstance(migration, asyncio.Future):
            await _drain_migration(migration)
        logger.exception(
            "Migration execution timed out",
            service=service_name,
            timeout_seconds=max_seconds,
        )
        msg = f"Migration timed out after {max_seconds}s"
        raise MigrationError(msg) from err
    except Exception as err:
        logger.exception(
            "Migration execution failed",
            service=service_name,
            error=str(err),
        )
        msg = f"Migration failed: {err}"
        raise MigrationError(msg) from err


def run_alembic_upgrade(config_path: str, db_url: str) -> None:
    """Execute Alembic upgrade to head with error handling."""
    logger.info(
        "Alembic upgrade starting",
        config_path=config_path,
        pid=os.getpid(),
    )

    if not Path(config_path).exists():
        msg = f"Alembic config not found: {config_path}"
        logger.error("Migration failed - config not found", config_path=config_path)
        set_migration_status("failed", error=msg)
        raise MigrationError(msg)

    sync_url = to_sync_url(db_url)

    try:
        cfg = Config(config_path)
        cfg.set_main_option("sqlalchemy.url", sync_url)
        cfg.set_main_option("script_location", "alembic")
        cfg.attributes["configure_logger"] = False

        logger.info(
            "Executing alembic upgrade to head",
            config_path=config_path,
            script_location="alembic",
        )
        alembic_command.upgrade(cfg, "head")
        logger.info(
            "Alembic upgrade completed",
            pid=os.getpid(),
        )

    except CommandError as err:
        msg = f"Alembic CommandError: {err}"
        logger.exception(
            "Migration failed - Alembic command error",
            error=str(err),
        )
        set_migration_status("failed", error=msg)
        raise MigrationError(msg) from err
    except SQLAlchemyError as err:
        msg = f"SQLAlchemy error during migration: {err}"
        logger.exception(
            "Migration failed - SQLAlchemy error",
            error=str(err),
            error_type=type(err).__name__,
        )
        set_migration_status("failed", error=msg)
        raise MigrationError(msg) from err
    except Exception as err:
        msg = f"Unexpected error during migration: {type(err).__name__}: {err}"
        logger.exception(
            "Migration failed - unexpected error",
            error=str(err),
            error_type=type(err).__name__,
        )
        set_migration_status("failed", error=msg)
        raise MigrationError(msg) from err

"""Main migration coordination orchestration.

Coordinates distributed migration execution using PostgreSQL advisory locks,
ensuring only one pod runs migrations while others wait.
"""

from __future__ import annotations

import os
import zlib
from datetime import UTC, datetime

from nohiki_observability import get_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from .executor import execute_migrations
from .lock import (
    clear_lock_metadata,
    ensure_lock_meta_table,
    get_lock_metadata,
    release_lock,
    set_lock_metadata,
    try_acquire_lock,
    wait_for_lock_release,
)
from .protocols import DatabaseSettingsProvider, LockContext
from .state import MigrationError, set_migration_status
from .url_utils import create_async_engine_with_ssl
from .version import check_migration_needed, get_db_version_info

logger = get_logger(__name__)

MIGRATION_LOCK_TIMEOUT_DEFAULT = 120


async def run_migrations_with_coordination(
    service_name: str,
    database_url: str | None = None,
    timeout_seconds: int = MIGRATION_LOCK_TIMEOUT_DEFAULT,
    alembic_config_path: str = "alembic.ini",
) -> None:
    """Run Alembic migrations with distributed coordination via PostgreSQL advisory locks.

    One pod acquires the lock and runs migrations. Other pods wait for the lock
    to be released, then proceed (Alembic upgrade is idempotent).

    Args:
        service_name: Used to generate a unique lock ID per service
        database_url: Database URL (if None, reads from secrets)
        timeout_seconds: Maximum wait time for lock acquisition or migration
        alembic_config_path: Path to alembic.ini

    Raises:
        MigrationError: If migration fails or times out

    """
    if not database_url:
        msg = "database_url is required"
        raise MigrationError(msg)
    if not database_url.startswith("postgresql"):
        msg = f"PostgreSQL required, got: {database_url[:20]}..."
        raise MigrationError(msg)

    pod_id = os.environ.get("HOSTNAME", os.environ.get("POD_NAME", f"pod-{os.getpid()}"))
    logger.info(
        "Migration runner starting",
        service=service_name,
        pod_id=pod_id,
        timeout_seconds=timeout_seconds,
    )

    needs_migration, head_rev = check_migration_needed(database_url, alembic_config_path, service_name)
    if not needs_migration:
        set_migration_status("completed", target_revision=head_rev, current_revision=head_rev)
        return

    set_migration_status("in_progress", target_revision=head_rev)

    lock_id = zlib.crc32(f"migration:{service_name}".encode()) & 0x7FFFFFFF
    logger.info(
        "Computed deterministic migration lock ID",
        service=service_name,
        lock_id=lock_id,
    )
    engine = create_async_engine_with_ssl(database_url, isolation_level="AUTOCOMMIT")

    lock_context = LockContext(service_name, pod_id, database_url, alembic_config_path)

    try:
        async with engine.connect() as conn:
            await ensure_lock_meta_table(conn)
            logger.info(
                "Acquiring migration lock",
                service=service_name,
                lock_id=lock_id,
            )
            acquired = await try_acquire_lock(conn, lock_id)

            if acquired:
                await _run_with_lock(conn, lock_id, lock_context, timeout_seconds, head_rev)
            else:
                await _handle_lock_not_acquired(conn, lock_id, timeout_seconds, lock_context)

    except MigrationError:
        raise
    except SQLAlchemyError as err:
        logger.exception("Database error during migration", service=service_name)
        msg = f"Database error: {err}"
        raise MigrationError(msg) from err
    finally:
        await engine.dispose()


async def _run_with_lock(
    conn: AsyncConnection,
    lock_id: int,
    ctx: LockContext,
    timeout_seconds: int,
    head_rev: str | None,
) -> None:
    """Execute migrations while holding the lock."""
    logger.info(
        "Migration lock acquired",
        service=ctx.service_name,
        pod_id=ctx.pod_id,
        lock_id=lock_id,
    )
    await set_lock_metadata(conn, lock_id, ctx.pod_id)

    try:
        await execute_migrations(ctx.service_name, ctx.database_url, timeout_seconds, ctx.alembic_config_path)
        final_rev, _ = get_db_version_info(ctx.database_url, ctx.alembic_config_path)

        set_migration_status("completed", current_revision=final_rev, target_revision=head_rev)

        logger.info(
            "Database migrations complete",
            service=ctx.service_name,
            status="success",
            final_version=final_rev,
            target_version=head_rev,
        )
    except Exception as err:
        set_migration_status("failed", error=str(err))
        raise
    finally:
        await clear_lock_metadata(conn, lock_id)
        await release_lock(conn, lock_id)
        logger.info(
            "Migration lock released",
            service=ctx.service_name,
            lock_id=lock_id,
        )


async def _handle_lock_not_acquired(
    conn: AsyncConnection,
    lock_id: int,
    timeout_seconds: int,
    context: LockContext,
) -> None:
    """Handle case when lock is held by another pod."""
    lock_meta = await get_lock_metadata(conn, lock_id)
    if lock_meta is None:
        msg = "Migration lock metadata missing"
        raise MigrationError(msg)

    acquired_at, holder_id = lock_meta
    age_seconds = (datetime.now(UTC) - acquired_at).total_seconds()

    logger.info(
        "Migration lock held by another pod",
        service=context.service_name,
        holder_pod=holder_id,
        lock_age_seconds=round(age_seconds, 1),
        max_wait_seconds=timeout_seconds,
    )

    if age_seconds > timeout_seconds:
        logger.warning(
            "Stale migration lock detected",
            service=context.service_name,
            holder_pod=holder_id,
            lock_age_seconds=round(age_seconds, 1),
            timeout_seconds=timeout_seconds,
        )
        logger.info("Waiting for stale lock to expire...", service=context.service_name)

    remaining_wait = max(0, timeout_seconds - age_seconds)
    if remaining_wait > 0:
        logger.info(
            "Waiting for lock release",
            service=context.service_name,
            max_wait_seconds=round(remaining_wait, 1),
        )

    await wait_for_lock_release(conn, lock_id, int(remaining_wait) + 5, context.service_name)

    current_rev, head_rev = get_db_version_info(context.database_url, context.alembic_config_path)

    if current_rev == head_rev:
        logger.info(
            "Database migrations complete (migrated by another pod)",
            service=context.service_name,
            status="success",
            current_version=current_rev,
        )
    else:
        logger.warning(
            "Database NOT up to date after lock release - other pod may have failed",
            service=context.service_name,
            current_version=current_rev,
            target_version=head_rev,
        )
        logger.info(
            "Acquiring lock to complete migration",
            service=context.service_name,
        )
        acquired = await try_acquire_lock(conn, lock_id)
        if acquired:
            logger.info(
                "Migration lock acquired (recovery)",
                service=context.service_name,
                pod_id=context.pod_id,
            )
            await set_lock_metadata(conn, lock_id, context.pod_id)
            try:
                await execute_migrations(
                    context.service_name,
                    context.database_url,
                    timeout_seconds,
                    context.alembic_config_path,
                )
                final_rev, _ = get_db_version_info(context.database_url, context.alembic_config_path)
                logger.info(
                    "Database migrations complete (recovery)",
                    service=context.service_name,
                    status="success",
                    final_version=final_rev,
                )
            finally:
                await clear_lock_metadata(conn, lock_id)
                await release_lock(conn, lock_id)
                logger.info(
                    "Migration lock released",
                    service=context.service_name,
                    lock_id=lock_id,
                )
        else:
            msg = "Failed to acquire lock for recovery migration"
            raise MigrationError(msg)


async def initialize_database(settings: DatabaseSettingsProvider) -> None:
    """Initialize database for a service: run migrations and ensure outbox schema.

    This is the single entry point for database initialization in service lifespan.
    Services simply call: `await initialize_database(settings)`

    Args:
        settings: Service settings implementing DatabaseSettingsProvider protocol.

    Raises:
        MigrationError: If migrations fail or database is not configured.

    """
    db = settings.database

    if db is None:
        msg = "Database configuration is required for initialize_database"
        raise MigrationError(msg)

    if db.migrate_on_startup:
        await run_migrations_with_coordination(
            settings.service_name,
            database_url=db.connection_string,
            timeout_seconds=db.migration_timeout_seconds,
        )

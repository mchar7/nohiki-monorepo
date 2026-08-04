"""Distributed seeding utility with advisory lock coordination.

Provides idempotent seed execution for multi-pod deployments using PostgreSQL
advisory locks. Only one pod runs seeding; others wait for completion.

Features:
- PostgreSQL advisory locks (no Redis dependency)
- Configurable timeouts and lock IDs
- logging with flush for async contexts
- Stale lock detection and recovery
- Version tracking to skip already-seeded data

Usage:
    async def seed_layouts(conn: AsyncConnection) -> None:
        # Your seeding logic here
        await conn.execute(insert(DocumentLayout).values(...))

    await run_seeding_with_coordination(
        service_name="doc-layout-service",
        database_url=settings.database.connection_string,
        seed_name="layouts",
        seed_version="1.0.0",
        seed_function=seed_layouts,
    )
"""

from __future__ import annotations

import asyncio
import os
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from sqlalchemy import (
    BigInteger,
    Column,
    MetaData,
    String,
    Table,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from nohiki_db_utils.migrations.url_utils import create_async_engine_with_ssl

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = get_logger(__name__)

# Default configuration
SEEDING_LOCK_TIMEOUT_DEFAULT = 120
SEEDING_POLL_INTERVAL = 1

# SQLAlchemy table definitions for seeding coordination
_seed_meta = MetaData()

seed_lock_meta_table = Table(
    "seed_lock_meta",
    _seed_meta,
    Column("lock_id", BigInteger, primary_key=True),
    Column("acquired_at", TIMESTAMP(timezone=True), nullable=False),
    Column("holder_id", String(255), nullable=False),
    Column("seed_name", String(255), nullable=False),
)

seed_versions_table = Table(
    "seed_versions",
    _seed_meta,
    Column("seed_name", String(255), primary_key=True),
    Column("version", String(100), nullable=False),
    Column("applied_at", TIMESTAMP(timezone=True), nullable=False),
    Column("applied_by", String(255), nullable=False),
)


class SeedingError(Exception):
    """Seeding failed - may prevent application startup."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        super().__init__(message)
        self.message = message


@dataclass(slots=True)
class SeedingState:
    """Global seeding state for health check integration."""

    status: str = "not_started"  # not_started, in_progress, completed, skipped, failed
    error: str | None = None
    seed_name: str | None = None
    seed_version: str | None = None
    started_at: float | None = None
    completed_at: float | None = None

    def is_healthy(self) -> bool:
        """Return True if seeding completed or was skipped."""
        return self.status in ("completed", "skipped")

    def to_dict(self) -> dict[str, str | float | bool | None]:
        """Convert to dictionary for health check response."""
        return {
            "status": self.status,
            "healthy": self.is_healthy(),
            "error": self.error,
            "seed_name": self.seed_name,
            "seed_version": self.seed_version,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True, slots=True)
class SeedContext:
    """Context for seeding operations."""

    service_name: str
    pod_id: str
    database_url: str
    seed_name: str
    seed_version: str
    timeout_seconds: int


# Type alias for seed function
SeedFunction = Callable[["AsyncConnection"], Awaitable[None]]


async def _ensure_seed_tables(conn: AsyncConnection) -> None:
    """Ensure seed coordination tables exist."""
    # Create seed_lock_meta table
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS seed_lock_meta (
                lock_id BIGINT PRIMARY KEY,
                acquired_at TIMESTAMPTZ NOT NULL,
                holder_id VARCHAR(255) NOT NULL,
                seed_name VARCHAR(255) NOT NULL
            )
            """
        )
    )

    # Create seed_versions table
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS seed_versions (
                seed_name VARCHAR(255) PRIMARY KEY,
                version VARCHAR(100) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL,
                applied_by VARCHAR(255) NOT NULL
            )
            """
        )
    )


async def _get_seed_version(conn: AsyncConnection, seed_name: str) -> str | None:
    """Get the current version of a seed, or None if not applied."""
    result = await conn.execute(
        select(seed_versions_table.c.version).where(seed_versions_table.c.seed_name == seed_name)
    )
    row = result.fetchone()
    return row.version if row else None


async def _set_seed_version(
    conn: AsyncConnection,
    seed_name: str,
    version: str,
    applied_by: str,
) -> None:
    """Record that a seed version has been applied."""
    now = datetime.now(UTC)
    stmt = pg_insert(seed_versions_table).values(
        seed_name=seed_name,
        version=version,
        applied_at=now,
        applied_by=applied_by,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=[seed_versions_table.c.seed_name],
        set_={"version": version, "applied_at": now, "applied_by": applied_by},
    )
    await conn.execute(upsert_stmt)
    await conn.commit()


async def _set_lock_metadata(
    conn: AsyncConnection,
    lock_id: int,
    holder_id: str,
    seed_name: str,
) -> None:
    """Record lock acquisition timestamp and holder."""
    now = datetime.now(UTC)
    stmt = pg_insert(seed_lock_meta_table).values(
        lock_id=lock_id,
        acquired_at=now,
        holder_id=holder_id,
        seed_name=seed_name,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=[seed_lock_meta_table.c.lock_id],
        set_={"acquired_at": now, "holder_id": holder_id, "seed_name": seed_name},
    )
    await conn.execute(upsert_stmt)
    await conn.commit()


async def _get_lock_metadata(
    conn: AsyncConnection,
    lock_id: int,
) -> tuple[datetime, str, str] | None:
    """Get lock acquisition timestamp, holder, and seed name."""
    result = await conn.execute(
        select(
            seed_lock_meta_table.c.acquired_at,
            seed_lock_meta_table.c.holder_id,
            seed_lock_meta_table.c.seed_name,
        ).where(seed_lock_meta_table.c.lock_id == lock_id)
    )
    row = result.fetchone()
    if row:
        return row.acquired_at, row.holder_id, row.seed_name
    return None


async def _clear_lock_metadata(conn: AsyncConnection, lock_id: int) -> None:
    """Clear lock metadata after release."""
    await conn.execute(delete(seed_lock_meta_table).where(seed_lock_meta_table.c.lock_id == lock_id))
    await conn.commit()


async def _try_acquire_lock(conn: AsyncConnection, lock_id: int) -> bool:
    """Attempt to acquire advisory lock without blocking."""
    result = await conn.execute(select(func.pg_try_advisory_lock(lock_id)))
    return bool(result.scalar())


async def _release_lock(conn: AsyncConnection, lock_id: int) -> None:
    """Release advisory lock."""
    await conn.execute(select(func.pg_advisory_unlock(lock_id)))


async def _wait_for_lock_release(
    conn: AsyncConnection,
    lock_id: int,
    max_wait_seconds: float,
    ctx: SeedContext,
) -> None:
    """Wait for another pod to finish seeding by polling for lock availability."""
    start_time = time.monotonic()
    deadline = start_time + max_wait_seconds
    elapsed = 0.0
    poll_count = 0

    while elapsed < max_wait_seconds:
        poll_count += 1
        if await _try_acquire_lock(conn, lock_id):
            await _release_lock(conn, lock_id)
            logger.info(
                "Seed lock released by holder",
                service=ctx.service_name,
                seed_name=ctx.seed_name,
                waited_seconds=round(elapsed, 1),
            )
            return

        await asyncio.sleep(min(SEEDING_POLL_INTERVAL, max(0.0, deadline - time.monotonic())))
        elapsed = time.monotonic() - start_time

        # Log progress every 10 polls
        if poll_count % 10 == 0:
            logger.info(
                "Still waiting for seed lock",
                service=ctx.service_name,
                seed_name=ctx.seed_name,
                elapsed_seconds=round(elapsed, 1),
                max_wait_seconds=max_wait_seconds,
            )

    msg = f"Timeout waiting for seed lock after {max_wait_seconds}s"
    logger.error(msg, service=ctx.service_name, seed_name=ctx.seed_name)
    raise SeedingError(msg)


async def _execute_seeding(
    conn: AsyncConnection,
    ctx: SeedContext,
    seed_function: SeedFunction,
) -> None:
    """Execute the seed function with timeout."""
    logger.info(
        "Starting seed execution",
        service=ctx.service_name,
        seed_name=ctx.seed_name,
        seed_version=ctx.seed_version,
        max_duration_seconds=ctx.timeout_seconds,
    )

    try:
        await asyncio.wait_for(
            seed_function(conn),
            timeout=ctx.timeout_seconds,
        )
        logger.info(
            "Seed execution completed",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
        )

    except TimeoutError as err:
        logger.exception(
            "Seeding execution timed out",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            timeout_seconds=ctx.timeout_seconds,
        )
        msg = f"Seeding timed out after {ctx.timeout_seconds}s"
        raise SeedingError(msg) from err
    except Exception as err:
        logger.exception(
            "Seeding execution failed",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            error=str(err),
        )
        msg = f"Seeding failed: {err}"
        raise SeedingError(msg) from err


async def _run_with_lock(
    conn: AsyncConnection,
    lock_id: int,
    ctx: SeedContext,
    seed_function: SeedFunction,
    state: SeedingState,
) -> None:
    """Execute seeding while holding the lock."""
    logger.info(
        "Seed lock acquired",
        service=ctx.service_name,
        pod_id=ctx.pod_id,
        seed_name=ctx.seed_name,
        lock_id=lock_id,
    )
    await _set_lock_metadata(conn, lock_id, ctx.pod_id, ctx.seed_name)

    try:
        await _execute_seeding(conn, ctx, seed_function)

        # Record successful seed version
        await _set_seed_version(conn, ctx.seed_name, ctx.seed_version, ctx.pod_id)

        state.status = "completed"
        state.completed_at = time.time()

        logger.info(
            "Seeding complete",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            seed_version=ctx.seed_version,
            status="success",
        )
    except Exception as err:
        state.status = "failed"
        state.error = str(err)
        state.completed_at = time.time()
        raise
    finally:
        await _clear_lock_metadata(conn, lock_id)
        await _release_lock(conn, lock_id)
        logger.info(
            "Seed lock released",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            lock_id=lock_id,
        )


async def _handle_lock_not_acquired(
    conn: AsyncConnection,
    lock_id: int,
    ctx: SeedContext,
    state: SeedingState,
) -> None:
    """Handle case when lock is held by another pod."""
    lock_meta = await _get_lock_metadata(conn, lock_id)
    if lock_meta is None:
        msg = "Seed lock metadata missing"
        raise SeedingError(msg)

    acquired_at, holder_id, _ = lock_meta
    age_seconds = (datetime.now(UTC) - acquired_at).total_seconds()

    logger.info(
        "Seed lock held by another pod",
        service=ctx.service_name,
        seed_name=ctx.seed_name,
        holder_pod=holder_id,
        lock_age_seconds=round(age_seconds, 1),
        max_wait_seconds=ctx.timeout_seconds,
    )

    if age_seconds > ctx.timeout_seconds:
        logger.warning(
            "Stale seed lock detected",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            holder_pod=holder_id,
            lock_age_seconds=round(age_seconds, 1),
            timeout_seconds=ctx.timeout_seconds,
        )

    remaining_wait = max(0, ctx.timeout_seconds - age_seconds)

    # Wait for lock release
    await _wait_for_lock_release(conn, lock_id, int(remaining_wait) + 5, ctx)

    # After lock released, check if seeding was completed
    current_version = await _get_seed_version(conn, ctx.seed_name)

    if current_version == ctx.seed_version:
        state.status = "skipped"
        state.completed_at = time.time()
        logger.info(
            "SEEDING COMPLETE (seeded by another pod)",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            seed_version=ctx.seed_version,
            status="skipped",
        )
    else:
        logger.warning(
            "Seed version mismatch after lock release - other pod may have failed",
            service=ctx.service_name,
            seed_name=ctx.seed_name,
            expected_version=ctx.seed_version,
            actual_version=current_version,
        )
        # Other pod failed - we should NOT attempt to seed here
        # The next startup attempt will try again
        msg = f"Seed version mismatch: expected {ctx.seed_version}, got {current_version}"
        state.status = "failed"
        state.error = msg
        raise SeedingError(msg)


@dataclass(frozen=True, slots=True)
class SeedingConfig:
    """Configuration for seeding coordination."""

    service_name: str
    database_url: str
    seed_name: str
    seed_version: str
    timeout_seconds: int = SEEDING_LOCK_TIMEOUT_DEFAULT


async def run_seeding_with_coordination(
    config: SeedingConfig,
    seed_function: SeedFunction,
) -> SeedingState:
    """Run seeding with distributed coordination via PostgreSQL advisory locks.

    One pod acquires the lock and runs seeding. Other pods wait for the lock
    to be released. Seeding is idempotent via version checking - if the target
    version is already applied, seeding is skipped.

    Args:
        config: Seeding configuration containing service_name, database_url,
            seed_name, seed_version, and timeout_seconds.
        seed_function: Async function that performs the actual seeding.
            Receives an AsyncConnection and should perform all seed operations.

    Returns:
        SeedingState with status and any error information.

    Raises:
        SeedingError: If seeding fails.

    Example:
        async def seed_layouts(conn: AsyncConnection) -> None:
            await conn.execute(insert(DocumentLayout).values(name="default", ...))
            await conn.commit()

        state = await run_seeding_with_coordination(
            service_name="doc-layout-service",
            database_url=settings.database.connection_string,
            seed_name="layouts",
            seed_version="1.0.0",
            seed_function=seed_layouts,
        )
        if not state.is_healthy():
            raise RuntimeError(f"Seeding failed: {state.error}")

    """
    pod_id = os.environ.get("HOSTNAME", os.environ.get("POD_NAME", f"pod-{os.getpid()}"))

    state = SeedingState(
        seed_name=config.seed_name,
        seed_version=config.seed_version,
        started_at=time.time(),
    )

    logger.info(
        "Seeding runner starting",
        service=config.service_name,
        pod_id=pod_id,
        seed_name=config.seed_name,
        seed_version=config.seed_version,
        timeout_seconds=config.timeout_seconds,
    )

    # Generate unique lock ID from service name and seed name
    lock_id = zlib.crc32(f"seed:{config.service_name}:{config.seed_name}".encode()) & 0x7FFFFFFF

    engine: AsyncEngine = create_async_engine_with_ssl(config.database_url, isolation_level="AUTOCOMMIT")

    ctx = SeedContext(
        service_name=config.service_name,
        pod_id=pod_id,
        database_url=config.database_url,
        seed_name=config.seed_name,
        seed_version=config.seed_version,
        timeout_seconds=config.timeout_seconds,
    )

    try:
        async with engine.connect() as conn:
            # Ensure coordination tables exist
            await _ensure_seed_tables(conn)

            # Check if target version already applied
            current_version = await _get_seed_version(conn, config.seed_name)
            if current_version == config.seed_version:
                state.status = "skipped"
                state.completed_at = time.time()
                logger.info(
                    "Seed already up to date",
                    service=config.service_name,
                    seed_name=config.seed_name,
                    current_version=current_version,
                    target_version=config.seed_version,
                )
                return state

            if current_version:
                logger.info(
                    "Seed requires update",
                    service=config.service_name,
                    seed_name=config.seed_name,
                    current_version=current_version,
                    target_version=config.seed_version,
                )
            else:
                logger.info(
                    "Seed not yet applied",
                    service=config.service_name,
                    seed_name=config.seed_name,
                    target_version=config.seed_version,
                )

            # Mark as in progress
            state.status = "in_progress"

            # Try to acquire lock
            logger.info(
                "Acquiring seed lock",
                service=config.service_name,
                seed_name=config.seed_name,
                lock_id=lock_id,
            )

            acquired = await _try_acquire_lock(conn, lock_id)

            if acquired:
                await _run_with_lock(conn, lock_id, ctx, seed_function, state)
            else:
                await _handle_lock_not_acquired(conn, lock_id, ctx, state)

    except SeedingError:
        raise
    except SQLAlchemyError as err:
        logger.exception(
            "Database error during seeding",
            service=config.service_name,
            seed_name=config.seed_name,
        )
        state.status = "failed"
        state.error = str(err)
        msg = f"Database error: {err}"
        raise SeedingError(msg) from err
    finally:
        await engine.dispose()

    return state

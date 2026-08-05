"""PostgreSQL advisory lock operations and metadata management.

Provides lock acquisition, release, waiting, and metadata tracking for distributed
migration coordination.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from nohiki_observability import get_logger
from sqlalchemy import BigInteger, Column, MetaData, String, Table, delete, func, select
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from .state import MigrationError

logger = get_logger(__name__)

LOCK_POLL_INTERVAL = 1

# Two-key advisory locks occupy a namespace separate from the one-key migration
# locks. This transaction-scoped lock serializes lock ownership and metadata.
LOCK_METADATA_GUARD_NAMESPACE = 0x4E4F4849

_lock_meta = MetaData()
lock_meta_table = Table(
    "alembic_lock_meta",
    _lock_meta,
    Column("lock_id", BigInteger, primary_key=True),
    Column("acquired_at", TIMESTAMP(timezone=True), nullable=False),
    Column("holder_id", String, nullable=False),
)


async def ensure_lock_meta_table(conn: AsyncConnection) -> None:
    """Ensure the lock metadata table exists using SQLAlchemy DDL."""
    await conn.run_sync(lambda sync_conn: lock_meta_table.create(sync_conn, checkfirst=True))


async def set_lock_metadata(conn: AsyncConnection, lock_id: int, holder_id: str) -> None:
    """Record lock acquisition timestamp and holder using SQLAlchemy Core."""
    now = datetime.now(UTC)
    stmt = pg_insert(lock_meta_table).values(
        lock_id=lock_id,
        acquired_at=now,
        holder_id=holder_id,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=[lock_meta_table.c.lock_id],
        set_={"acquired_at": now, "holder_id": holder_id},
    )
    await conn.execute(upsert_stmt)


async def get_lock_metadata(conn: AsyncConnection, lock_id: int) -> tuple[datetime, str] | None:
    """Get lock acquisition timestamp and holder using SQLAlchemy Core."""
    stmt = select(lock_meta_table.c.acquired_at, lock_meta_table.c.holder_id).where(
        lock_meta_table.c.lock_id == lock_id
    )
    result = await conn.execute(stmt)
    row = result.fetchone()
    if row:
        return row.acquired_at, row.holder_id
    return None


async def clear_lock_metadata(conn: AsyncConnection, lock_id: int) -> None:
    """Clear lock metadata after release using SQLAlchemy Core."""
    stmt = delete(lock_meta_table).where(lock_meta_table.c.lock_id == lock_id)
    await conn.execute(stmt)


async def try_acquire_lock(conn: AsyncConnection, lock_id: int) -> bool:
    """Attempt to acquire advisory lock without blocking using SQLAlchemy func."""
    stmt = select(func.pg_try_advisory_lock(lock_id))
    result = await conn.execute(stmt)
    return bool(result.scalar())


async def _acquire_metadata_guard(conn: AsyncConnection, lock_id: int) -> None:
    """Serialize advisory-lock ownership changes with metadata changes."""
    await conn.execute(select(func.pg_advisory_xact_lock(LOCK_METADATA_GUARD_NAMESPACE, lock_id)))


async def acquire_lock_with_metadata(
    conn: AsyncConnection,
    lock_id: int,
    holder_id: str,
) -> tuple[bool, tuple[datetime, str] | None]:
    """Acquire the lock and observe holder metadata under the same guard."""
    await _acquire_metadata_guard(conn, lock_id)
    acquired = False
    try:
        acquired = await try_acquire_lock(conn, lock_id)
        metadata = None
        if acquired:
            await set_lock_metadata(conn, lock_id, holder_id)
        else:
            metadata = await get_lock_metadata(conn, lock_id)
        await conn.commit()
    except Exception, asyncio.CancelledError:
        try:
            if acquired:
                await release_lock(conn, lock_id)
        finally:
            await conn.rollback()
        raise
    return acquired, metadata


async def release_lock(conn: AsyncConnection, lock_id: int) -> None:
    """Release advisory lock using SQLAlchemy func."""
    stmt = select(func.pg_advisory_unlock(lock_id))
    await conn.execute(stmt)


async def release_lock_with_metadata(conn: AsyncConnection, lock_id: int) -> None:
    """Release the lock and remove its metadata as one observable transition."""
    await _acquire_metadata_guard(conn, lock_id)
    try:
        await release_lock(conn, lock_id)
        await clear_lock_metadata(conn, lock_id)
        await conn.commit()
    except Exception, asyncio.CancelledError:
        await conn.rollback()
        raise


async def probe_lock_released(conn: AsyncConnection, lock_id: int) -> bool:
    """Report whether the lock is free, without ever owning it observably.

    The probe takes the lock to learn it is free, which makes the prober a momentary owner
    with no metadata row. Holding the metadata guard across the probe keeps that momentary
    ownership invisible to a contender in ``acquire_lock_with_metadata``, which would
    otherwise read no metadata and treat that state as impossible.
    """
    await _acquire_metadata_guard(conn, lock_id)
    try:
        released = await try_acquire_lock(conn, lock_id)
        if released:
            await release_lock(conn, lock_id)
        await conn.commit()
    except Exception, asyncio.CancelledError:
        await conn.rollback()
        raise
    return released


async def wait_for_lock_release(
    conn: AsyncConnection,
    lock_id: int,
    max_wait_seconds: float,
    service_name: str,
) -> None:
    """Wait for another pod to finish migrations by polling for lock availability."""
    start_time = time.monotonic()
    deadline = start_time + max_wait_seconds
    elapsed = 0.0
    poll_count = 0

    while elapsed < max_wait_seconds:
        poll_count += 1
        if await probe_lock_released(conn, lock_id):
            logger.info(
                "Migration lock released by holder",
                service=service_name,
                waited_seconds=round(elapsed, 1),
            )
            return

        await asyncio.sleep(min(LOCK_POLL_INTERVAL, max(0.0, deadline - time.monotonic())))
        elapsed = time.monotonic() - start_time

        if poll_count % 10 == 0:
            logger.info(
                "Still waiting for migration lock",
                service=service_name,
                elapsed_seconds=round(elapsed, 1),
                max_wait_seconds=max_wait_seconds,
            )

    msg = f"Timeout waiting for migration lock after {max_wait_seconds}s"
    logger.error(msg, service=service_name)
    raise MigrationError(msg)

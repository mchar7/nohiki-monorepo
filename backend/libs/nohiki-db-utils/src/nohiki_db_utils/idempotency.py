"""Handler-level idempotency via processed_events table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from sqlalchemy import Column, DateTime, MetaData, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def check_and_mark_processed(
    db: AsyncSession,
    schema: str,
    event_id: str,
    handler_name: str,
) -> bool:
    """Check if an event has already been processed by this handler.

    Uses INSERT ... ON CONFLICT DO NOTHING for atomic check-and-mark.
    The caller's transaction commit makes the mark durable.

    Args:
        db: Async SQLAlchemy session (must be within a transaction).
        schema: Database schema containing the processed_events table.
        event_id: Unique event identifier (from EventMetadata.event_id).
        handler_name: Handler function name for per-handler deduplication.

    Returns:
        True if the event is NEW (not yet processed).
        False if the event was ALREADY processed (duplicate).

    """
    table = Table(
        "processed_events",
        MetaData(),
        Column("event_id", UUID(), primary_key=True),
        Column("handler_name", String, primary_key=True),
        Column("processed_at", DateTime(timezone=True)),
        schema=schema,
    )
    stmt = (
        pg_insert(table)
        .values(
            event_id=uuid.UUID(event_id),
            handler_name=handler_name,
            processed_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["event_id", "handler_name"])
        .returning(table.c.event_id)
    )
    result = await db.execute(stmt)
    row = result.fetchone()
    if row is None:
        logger.debug(
            "Duplicate event detected, skipping",
            event_id=event_id,
            handler_name=handler_name,
        )
        return False
    return True

"""TTL sweep contract against a real Postgres.

The sweep's correctness is a SQL property: the claim must touch exactly the rows
still awaiting delivery whose ``expires_at`` has elapsed, its locking must let a
second sweeping pod run beside it without blocking or double-cancelling, and the
lifecycle event must land in the same committed transaction as the cancellation.
All of that depends on Postgres semantics that a mocked session cannot demonstrate.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from nohiki_db_utils.outbox_migrations import get_create_outbox_table_sql
from notification_service.db.models import Base, Message, MessageStatus, NotificationChannelDB
from notification_service.services.outbox.expiry_sweep import EXPIRED_ERROR, MessageExpirySweep
from sqlalchemy import select, text

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

_SCHEMA = "notification_schema"

_EXPECTED_CANCELLED = 4
"""One row per expirable state, plus the cap-deferred row that must not be lost."""


@pytest.fixture
async def messages_schema(async_engine: AsyncEngine) -> AsyncGenerator[None]:
    """Create the notification_schema, messages table and outbox, drop on teardown."""
    async with async_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
        # The sweep publishes through the transactional outbox, so the real table
        # has to exist for the atomicity claim to be tested at all.
        await conn.execute(text(get_create_outbox_table_sql(_SCHEMA)))
    try:
        yield
    finally:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))


def _message(
    label: str,
    *,
    status: MessageStatus,
    expires_at: datetime | None,
    retry_at: datetime | None = None,
) -> Message:
    return Message(
        channel=NotificationChannelDB.EMAIL,
        recipient=f"{label}@example.com",
        status=status,
        priority=0,
        expires_at=expires_at,
        retry_at=retry_at,
        sent_at=datetime.now(UTC) if status is MessageStatus.SENT else None,
    )


async def _seed(session: AsyncSession) -> dict[str, UUID]:
    """Insert one row per case the sweep must distinguish."""
    past = datetime.now(UTC) - timedelta(minutes=5)
    future = datetime.now(UTC) + timedelta(hours=1)
    rows = {
        "expired_pending": _message("expired-pending", status=MessageStatus.PENDING, expires_at=past),
        "expired_retrying": _message("expired-retrying", status=MessageStatus.RETRYING, expires_at=past),
        "expired_waiting_render": _message(
            "expired-waiting-render", status=MessageStatus.WAITING_FOR_RENDER, expires_at=past
        ),
        "cap_deferred": _message("cap-deferred", status=MessageStatus.PENDING, expires_at=past, retry_at=future),
        "expired_failed": _message("expired-failed", status=MessageStatus.FAILED, expires_at=past),
        "unexpired_pending": _message("unexpired-pending", status=MessageStatus.PENDING, expires_at=future),
        "no_expiry_pending": _message("no-expiry-pending", status=MessageStatus.PENDING, expires_at=None),
        "expired_sent": _message("expired-sent", status=MessageStatus.SENT, expires_at=past),
    }
    session.add_all(list(rows.values()))
    await session.flush()
    ids = {label: row.id for label, row in rows.items()}
    await session.commit()
    return ids


async def _statuses(
    session_factory: async_sessionmaker[AsyncSession],
    ids: dict[str, UUID],
) -> dict[str, MessageStatus]:
    async with session_factory() as session:
        result = await session.execute(select(Message).where(Message.id.in_(list(ids.values()))))
        by_id = {row.id: row for row in result.scalars().all()}
    return {label: by_id[row_id].status for label, row_id in ids.items()}


async def _outbox_types(
    session_factory: async_sessionmaker[AsyncSession],
    aggregate_id: UUID,
) -> list[str]:
    async with session_factory() as session:
        result = await session.execute(
            text(f"SELECT type FROM {_SCHEMA}.outbox WHERE aggregateid = :aggregate_id"),
            {"aggregate_id": str(aggregate_id)},
        )
        return [row.type for row in result]


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_sweep_cancels_only_elapsed_rows_awaiting_delivery(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every elapsed non-terminal row is cancelled; terminal and permanently failed rows are not."""
    async with async_session_factory() as setup:
        ids = await _seed(setup)

    sweep = MessageExpirySweep(shutdown=asyncio.Event(), interval_seconds=300, batch_size=500)
    async with async_session_factory() as session:
        cancelled = await sweep.sweep_once(session)

    assert cancelled == _EXPECTED_CANCELLED

    statuses = await _statuses(async_session_factory, ids)
    assert statuses["expired_pending"] is MessageStatus.CANCELLED
    assert statuses["expired_retrying"] is MessageStatus.CANCELLED
    assert statuses["expired_waiting_render"] is MessageStatus.CANCELLED
    assert statuses["cap_deferred"] is MessageStatus.CANCELLED
    assert statuses["expired_failed"] is MessageStatus.FAILED
    assert statuses["unexpired_pending"] is MessageStatus.PENDING
    assert statuses["no_expiry_pending"] is MessageStatus.PENDING
    assert statuses["expired_sent"] is MessageStatus.SENT


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_sweep_records_the_expiry_reason(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A cancelled row carries the expiry reason, not a provider error."""
    async with async_session_factory() as setup:
        ids = await _seed(setup)

    sweep = MessageExpirySweep(shutdown=asyncio.Event(), interval_seconds=300, batch_size=500)
    async with async_session_factory() as session:
        await sweep.sweep_once(session)

    async with async_session_factory() as session:
        expired = await session.get(Message, ids["expired_pending"])
        untouched = await session.get(Message, ids["unexpired_pending"])

    assert expired is not None
    assert untouched is not None
    assert expired.last_error == EXPIRED_ERROR
    assert untouched.last_error is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_each_expired_row_commits_exactly_one_outbox_event(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The lifecycle event survives the same commit as the status change."""
    async with async_session_factory() as setup:
        ids = await _seed(setup)

    sweep = MessageExpirySweep(shutdown=asyncio.Event(), interval_seconds=300, batch_size=500)
    async with async_session_factory() as session:
        await sweep.sweep_once(session)

    assert await _outbox_types(async_session_factory, ids["expired_pending"]) == ["notification.fct.failed.v1"]
    assert await _outbox_types(async_session_factory, ids["unexpired_pending"]) == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_a_cap_deferred_row_reaching_its_ttl_is_not_silently_lost(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A cap denial parks a PENDING row on a future ``retry_at``; its loss must be published."""
    async with async_session_factory() as setup:
        ids = await _seed(setup)

    sweep = MessageExpirySweep(shutdown=asyncio.Event(), interval_seconds=300, batch_size=500)
    async with async_session_factory() as session:
        await sweep.sweep_once(session)

    async with async_session_factory() as session:
        deferred = await session.get(Message, ids["cap_deferred"])

    assert deferred is not None
    assert deferred.status is MessageStatus.CANCELLED
    assert deferred.retry_at is None, "a cancelled row must not keep a pending retry time"
    assert await _outbox_types(async_session_factory, ids["cap_deferred"]) == ["notification.fct.failed.v1"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_second_sweep_finds_nothing_left(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The sweep is idempotent: a cancelled row is no longer a candidate."""
    async with async_session_factory() as setup:
        await _seed(setup)

    sweep = MessageExpirySweep(shutdown=asyncio.Event(), interval_seconds=300, batch_size=500)
    async with async_session_factory() as session:
        first = await sweep.sweep_once(session)
    async with async_session_factory() as session:
        second = await sweep.sweep_once(session)

    assert first == _EXPECTED_CANCELLED
    assert second == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_two_concurrent_sweeps_cancel_each_row_once(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SKIP LOCKED keeps a second sweeping pod from re-cancelling the same rows."""
    async with async_session_factory() as setup:
        ids = await _seed(setup)

    sweep = MessageExpirySweep(shutdown=asyncio.Event(), interval_seconds=300, batch_size=500)

    async def _pass() -> int:
        async with async_session_factory() as session:
            return await sweep.sweep_once(session)

    async with asyncio.TaskGroup() as tg:
        first = tg.create_task(_pass())
        second = tg.create_task(_pass())

    assert first.result() + second.result() == _EXPECTED_CANCELLED, "each expired row is cancelled by exactly one pod"

    statuses = await _statuses(async_session_factory, ids)
    assert statuses["expired_pending"] is MessageStatus.CANCELLED
    assert statuses["expired_retrying"] is MessageStatus.CANCELLED
    assert statuses["unexpired_pending"] is MessageStatus.PENDING
    assert await _outbox_types(async_session_factory, ids["expired_pending"]) == ["notification.fct.failed.v1"], (
        "a row cancelled by one pod must not be published twice"
    )

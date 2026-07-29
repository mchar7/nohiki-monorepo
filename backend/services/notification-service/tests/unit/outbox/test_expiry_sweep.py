"""Message TTL sweep contract.

Three things are asserted here: the claim carries the same multi-pod locking
discipline the outbox claim uses, every expired row emits exactly one lifecycle
event inside the same transaction as its status change, and the loop lives and
dies with the worker's shared shutdown event. Which rows actually change is
proven against a real Postgres in ``tests/integration/test_expiry_sweep.py``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from notification_service.db.models import Message, MessageStatus, NotificationChannelDB
from notification_service.services.outbox.event_publisher import NotificationEventPublisher
from notification_service.services.outbox.expiry_sweep import EXPIRED_ERROR, MessageExpirySweep
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.sql import ClauseElement


def _compile(statement: ClauseElement) -> str:
    """Render a statement as Postgres SQL with values inlined."""
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _message(
    label: str,
    *,
    status: MessageStatus = MessageStatus.PENDING,
    retry_at: datetime | None = None,
) -> Message:
    """Build an unpersisted row already past its TTL."""
    return Message(
        channel=NotificationChannelDB.EMAIL,
        recipient=f"{label}@example.com",
        status=status,
        priority=0,
        retry_count=0,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
        retry_at=retry_at,
    )


def _claim_result(rows: Sequence[Message] = ()) -> MagicMock:
    """Result double standing in for the claim query's ORM rows."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    return result


def _claiming_session(rows: Sequence[Message] = ()) -> AsyncMock:
    """Session double whose claim query yields ``rows``."""
    session = AsyncMock()
    session.execute.return_value = _claim_result(rows)
    return session


def _session_factory(rows: Sequence[Message] = ()) -> MagicMock:
    """Session-factory double yielding a session whose claim returns ``rows``."""
    session = _claiming_session(rows)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


def _sweep(
    shutdown: asyncio.Event | None = None,
    *,
    interval: float = 300,
    batch: int = 500,
    publisher: AsyncMock | None = None,
) -> MessageExpirySweep:
    return MessageExpirySweep(
        shutdown=shutdown or asyncio.Event(),
        interval_seconds=interval,
        batch_size=batch,
        event_publisher=publisher or AsyncMock(spec=NotificationEventPublisher),
    )


class TestClaimQuery:
    """The sweep claims rows the same way the worker does."""

    def test_claim_locks_and_skips_locked_rows(self) -> None:
        """Concurrent sweeps and the worker must never block each other."""
        sql = _compile(MessageExpirySweep.build_expired_query(limit=7))

        assert "FOR UPDATE" in sql
        assert "SKIP LOCKED" in sql

    def test_claim_covers_every_state_still_awaiting_delivery(self) -> None:
        """A render callback that never arrives must not park a row past its TTL."""
        sql = _compile(MessageExpirySweep.build_expired_query(limit=7))

        assert "status IN ('pending', 'waiting_for_render', 'retrying')" in sql

    def test_claim_leaves_terminal_and_permanently_failed_rows_alone(self) -> None:
        """Expiring those would rewrite an outcome already reported downstream."""
        sql = _compile(MessageExpirySweep.build_expired_query(limit=7))

        assert "'sent'" not in sql
        assert "'cancelled'" not in sql
        assert "'failed'" not in sql

    def test_claim_only_matches_elapsed_expiries(self) -> None:
        """Predicate matches the partial index and excludes NULL expiries."""
        sql = _compile(MessageExpirySweep.build_expired_query(limit=7))

        assert "expires_at IS NOT NULL" in sql
        assert "expires_at <= now()" in sql

    def test_claim_does_not_filter_on_retry_at(self) -> None:
        """A cap-deferred row carries a future ``retry_at`` and must still be claimable."""
        where = _compile(MessageExpirySweep.build_expired_query(limit=7)).partition("WHERE")[2]

        assert "retry_at" not in where

    def test_claim_honours_the_batch_size(self) -> None:
        """The batch bound reaches the SQL, so a pass stays bounded."""
        assert "LIMIT 7" in _compile(MessageExpirySweep.build_expired_query(limit=7))


class TestExpiryIsObservable:
    """Every expired row leaves a lifecycle event behind, in its own transaction."""

    @pytest.mark.asyncio
    async def test_expired_row_is_cancelled_with_the_expiry_reason(self) -> None:
        """Operators can tell an expiry apart from a provider failure."""
        message = _message("expired")
        db = _claiming_session([message])

        await _sweep().sweep_once(db)

        assert message.status is MessageStatus.CANCELLED
        assert message.last_error == EXPIRED_ERROR
        assert message.retry_at is None

    @pytest.mark.asyncio
    async def test_each_expired_row_emits_exactly_one_event(self) -> None:
        """No downstream consumer can observe a loss that was never published."""
        publisher = AsyncMock(spec=NotificationEventPublisher)
        rows = [_message("first"), _message("second")]
        db = _claiming_session(rows)

        await _sweep(publisher=publisher).sweep_once(db)

        assert publisher.publish_failed.await_count == len(rows)
        assert [call.args[1] for call in publisher.publish_failed.await_args_list] == rows

    @pytest.mark.asyncio
    async def test_the_event_is_written_before_the_commit(self) -> None:
        """Outbox row and status change must land in one transaction, or neither."""
        order: list[str] = []
        publisher = AsyncMock(spec=NotificationEventPublisher)
        publisher.publish_failed.side_effect = lambda *_args: order.append("publish")
        db = _claiming_session([_message("expired")])
        db.commit.side_effect = lambda: order.append("commit")

        await _sweep(publisher=publisher).sweep_once(db)

        assert order == ["publish", "commit"]

    @pytest.mark.asyncio
    async def test_a_cap_deferred_row_reaching_its_ttl_is_not_silently_lost(self) -> None:
        """A cap denial parks a PENDING row on a future ``retry_at``; expiry must still be published."""
        publisher = AsyncMock(spec=NotificationEventPublisher)
        deferred = _message("capped", retry_at=datetime.now(UTC) + timedelta(hours=1))
        db = _claiming_session([deferred])

        assert await _sweep(publisher=publisher).sweep_once(db) == 1

        assert deferred.status is MessageStatus.CANCELLED
        publisher.publish_failed.assert_awaited_once_with(db, deferred)

    @pytest.mark.asyncio
    async def test_a_row_awaiting_render_is_expired_too(self) -> None:
        """``WAITING_FOR_RENDER`` is stamped with a TTL like any other row."""
        publisher = AsyncMock(spec=NotificationEventPublisher)
        stuck = _message("unrendered", status=MessageStatus.WAITING_FOR_RENDER)
        db = _claiming_session([stuck])

        await _sweep(publisher=publisher).sweep_once(db)

        assert stuck.status is MessageStatus.CANCELLED
        publisher.publish_failed.assert_awaited_once_with(db, stuck)


class TestSweepOnce:
    """One pass reports what it changed and commits it."""

    @pytest.mark.asyncio
    async def test_returns_the_claimed_row_count(self) -> None:
        """The caller learns how many messages were cancelled."""
        db = _claiming_session([_message("a"), _message("b"), _message("c")])

        assert await _sweep().sweep_once(db) == 3
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_an_idle_pass_reports_zero_and_opens_no_transaction(self) -> None:
        """An empty claim is not an error and must not cost a commit."""
        publisher = AsyncMock(spec=NotificationEventPublisher)
        db = _claiming_session()

        assert await _sweep(publisher=publisher).sweep_once(db) == 0
        db.commit.assert_not_awaited()
        publisher.publish_failed.assert_not_awaited()


class TestRunLoop:
    """Lifecycle is driven by the shared shutdown event."""

    @pytest.mark.asyncio
    async def test_exits_immediately_when_shutdown_is_already_set(self) -> None:
        """A sweep started during shutdown does no work."""
        shutdown = asyncio.Event()
        shutdown.set()
        factory = _session_factory()

        await asyncio.wait_for(_sweep(shutdown).run_loop(factory), timeout=1)

        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_exits_when_the_shared_event_is_set_mid_wait(self) -> None:
        """Setting the worker's event stops the sweep without cancellation."""
        shutdown = asyncio.Event()
        factory = _session_factory()

        task = asyncio.create_task(_sweep(shutdown, interval=30).run_loop(factory))
        await asyncio.sleep(0)
        shutdown.set()

        await asyncio.wait_for(task, timeout=1)
        assert task.exception() is None
        assert factory.call_count == 1, "the pass in flight completes before exit"

    @pytest.mark.asyncio
    async def test_a_failed_pass_does_not_kill_the_loop(self) -> None:
        """A DB outage costs one pass, not the task."""
        shutdown = asyncio.Event()
        factory = _session_factory()
        session = await factory.return_value.__aenter__()
        passes = 0

        async def _execute(_statement: object) -> MagicMock:
            nonlocal passes
            passes += 1
            if passes == 1:
                msg = "connection reset"
                raise RuntimeError(msg)
            shutdown.set()
            return _claim_result()

        session.execute = _execute

        await asyncio.wait_for(_sweep(shutdown, interval=0.01).run_loop(factory), timeout=2)

        assert passes == 2, "the loop must survive the first failure and run again"

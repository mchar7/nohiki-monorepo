"""Multi-pod safety contract: two concurrent claims never overlap.

Two replicas of notification-service must be able to run concurrently
against the same DB without ever double-delivering a message. This test
proves that contract at the SQL level: two concurrent transactions each
run ``OutboxWorker._build_pending_query`` against the same table, and the
row sets they receive must be disjoint, because ``FOR UPDATE SKIP LOCKED``
skips rows the other transaction has locked.

Worker-level concurrency is then verified end-to-end by running two
``OutboxWorker._drain_batch`` calls concurrently against the same DB with
mocked routers, asserting each message is dispatched exactly once.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import AsyncMock

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_redis_utils import CircuitBreakerConfig
from notification_service.core.providers import (
    BaseProvider,
    EmailConfig,
    ProviderResult,
    clear_provider_registry,
    configure_email_provider,
    register_provider,
)
from notification_service.db.models import Base, Message, MessageStatus, NotificationChannelDB
from notification_service.services.outbox.provider_router import ProviderRouter
from notification_service.services.outbox.worker import OutboxWorker
from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


_SCHEMA = "notification_schema"


@pytest.fixture
async def messages_schema(async_engine: AsyncEngine) -> AsyncGenerator[None]:
    """Create the notification_schema and messages table, drop on teardown."""
    async with async_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))


async def _insert_pending_messages(session: AsyncSession, count: int) -> list[UUID]:
    """Insert ``count`` PENDING email messages and return their IDs."""
    messages = [
        Message(
            channel=NotificationChannelDB.EMAIL,
            recipient=f"user{i}@example.com",
            status=MessageStatus.PENDING,
            priority=0,
        )
        for i in range(count)
    ]
    session.add_all(messages)
    await session.flush()
    ids = [m.id for m in messages]
    await session.commit()
    return ids


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema")
async def test_two_concurrent_claims_return_disjoint_rows(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SELECT FOR UPDATE SKIP LOCKED in two transactions => no overlap."""
    async with async_session_factory() as setup:
        await _insert_pending_messages(setup, count=10)

    started_a = asyncio.Event()
    started_b = asyncio.Event()
    release = asyncio.Event()

    async def _claim(start_signal: asyncio.Event) -> set[UUID]:
        async with async_session_factory() as session:
            stmt = OutboxWorker._build_pending_query(limit=5)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            start_signal.set()
            # Hold the transaction open until both claims have been made, so
            # the second SELECT genuinely competes with the first one's locks.
            await release.wait()
            return {row.id for row in rows}

    async with asyncio.TaskGroup() as tg:
        task_a = tg.create_task(_claim(started_a))
        task_b = tg.create_task(_claim(started_b))
        await started_a.wait()
        await started_b.wait()
        release.set()

    claimed_a = task_a.result()
    claimed_b = task_b.result()

    assert len(claimed_a) == 5
    assert len(claimed_b) == 5
    assert claimed_a.isdisjoint(claimed_b)
    assert len(claimed_a | claimed_b) == 10


class _RecordingProvider(BaseProvider):
    """Provider that records every message it sends and always returns success."""

    channel = NotificationChannel.EMAIL
    name: ClassVar[str] = "recorder"
    required_secrets: ClassVar[list[str]] = []
    sent: ClassVar[list[UUID]] = []

    async def send(self, message: Message) -> ProviderResult:
        _RecordingProvider.sent.append(message.id)
        return ProviderResult(success=True, provider_msg_id=f"rec-{message.id}")

    async def validate_config(self) -> bool:
        return True


@pytest.fixture
def _recording_provider_registry() -> Generator[None]:
    """Register a single recording provider and clear it on teardown."""
    clear_provider_registry()
    _RecordingProvider.sent = []
    register_provider(NotificationChannel.EMAIL, _RecordingProvider)
    configure_email_provider(
        EmailConfig(from_address="from@example.com", from_name="t", unsubscribe_domain="example.com"),
        "recorder",
    )
    yield
    clear_provider_registry()
    _RecordingProvider.sent = []


@pytest.mark.asyncio
@pytest.mark.usefixtures("messages_schema", "_recording_provider_registry")
async def test_two_workers_dispatch_each_message_exactly_once(
    async_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two ``OutboxWorker`` instances draining concurrently never double-send."""
    async with async_session_factory() as setup:
        ids = await _insert_pending_messages(setup, count=10)
    assert len(ids) == 10

    # Redirect db_session inside the worker to our test session factory.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _test_db_session(_db_settings: object) -> AsyncGenerator[AsyncSession]:
        async with async_session_factory() as session:
            yield session

    monkeypatch.setattr(
        "notification_service.services.outbox.worker.db_session",
        _test_db_session,
    )
    # The worker also calls publish_sent which writes to an outbox table; stub
    # it so the test stays focused on the claim/dispatch contract.
    from notification_service.services.outbox import event_publisher as ep

    monkeypatch.setattr(ep.NotificationEventPublisher, "publish_sent", AsyncMock())
    monkeypatch.setattr(ep.NotificationEventPublisher, "publish_failed", AsyncMock())

    def _build_worker() -> OutboxWorker:
        return OutboxWorker(provider_router=ProviderRouter(cb_config=CircuitBreakerConfig()))

    worker_a = _build_worker()
    worker_b = _build_worker()

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_drain_until_empty(worker_a))
        tg.create_task(_drain_until_empty(worker_b))

    sent_ids = _RecordingProvider.sent
    assert sorted(sent_ids) == sorted(ids), "every message must be dispatched exactly once"
    assert len(sent_ids) == len(set(sent_ids)), "no message should be dispatched twice"


async def _drain_until_empty(worker: OutboxWorker, max_cycles: int = 20) -> None:
    """Drive ``worker._drain_batch`` until it processes nothing in a full cycle."""
    for _ in range(max_cycles):
        before = worker.metrics["messages_processed"]
        await worker._drain_batch()
        if worker.metrics["messages_processed"] == before:
            return

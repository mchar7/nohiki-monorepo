"""Unit tests for the OutboxWorker.

Exercises three things the worker is responsible for: the SKIP LOCKED claim
query, cooperative shutdown via :class:`asyncio.Event`, and the
``SendOutcome`` -> DB transition mapping. The :class:`ProviderRouter` and DB
session are both mocked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_db_utils.testing import create_mock_session
from nohiki_redis_utils import RateLimitFailurePolicy, RateLimitResult, create_token_bucket_limiter
from notification_service.core.providers import ProviderResult
from notification_service.db.models import Message, MessageStatus
from notification_service.services.frequency_checker import FrequencyChecker
from notification_service.services.outbox import OutboxWorker
from notification_service.services.outbox.event_publisher import NotificationEventPublisher
from notification_service.services.outbox.expiry_sweep import EXPIRED_ERROR
from notification_service.services.outbox.provider_router import ProviderRouter, SendOutcome, SendVerdict
from notification_service.services.outbox.retry_strategy import RetryDecision, RetryStrategy
from notification_service.services.outbox.worker import MIN_THROTTLE_DEFER_SECONDS
from redis.asyncio import RedisError
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Iterable


def _make_router(**overrides: object) -> MagicMock:
    """Spec'd ``ProviderRouter`` mock with a default DELIVERED ``send``.

    Returns a :class:`MagicMock` rather than a typed router so tests can call
    ``router.send.assert_awaited_once_with(...)`` and friends.
    """
    router = MagicMock(spec=ProviderRouter)
    router.send = AsyncMock(return_value=_delivered_outcome())
    for name, value in overrides.items():
        setattr(router, name, value)
    return router


def _delivered_outcome(provider_name: str = "resend", provider_msg_id: str = "msg_123") -> SendOutcome:
    provider = MagicMock()
    provider.name = provider_name
    return SendOutcome(
        verdict=SendVerdict.DELIVERED,
        provider=provider,
        result=ProviderResult(success=True, provider_msg_id=provider_msg_id),
    )


def _failed_outcome(*, retryable: bool, error: str = "boom") -> SendOutcome:
    provider = MagicMock()
    provider.name = "resend"
    return SendOutcome(
        verdict=SendVerdict.FAILED,
        provider=provider,
        result=ProviderResult(success=False, error=error, retryable=retryable),
    )


def _all_open_outcome() -> SendOutcome:
    return SendOutcome(verdict=SendVerdict.ALL_CIRCUITS_OPEN, provider=None, result=None)


def _make_message(*, expires_at: datetime | None = None, user_id: UUID | None = None) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.id = uuid4()
    msg.retry_count = 0
    msg.provider_name = "resend"
    msg.expires_at = expires_at
    msg.user_id = user_id
    msg.channel = MagicMock()
    msg.channel.to_proto.return_value = NotificationChannel.EMAIL
    return msg


class TestOutboxWorkerInit:
    """Initialisation contract."""

    def test_init_defaults(self) -> None:
        """Worker initialises ready-to-run with default sub-components."""
        worker = OutboxWorker(provider_router=_make_router())

        assert worker.is_running is True
        assert worker.rate_limiter is None
        assert isinstance(worker._retry_strategy, RetryStrategy)
        assert isinstance(worker._event_publisher, NotificationEventPublisher)

    def test_init_custom_components(self) -> None:
        """Custom sub-components are honoured."""
        router = _make_router()
        mock_limiter = MagicMock()
        mock_strategy = MagicMock(spec=RetryStrategy)
        mock_publisher = MagicMock(spec=NotificationEventPublisher)

        worker = OutboxWorker(
            provider_router=router,
            rate_limiter=mock_limiter,
            retry_strategy=mock_strategy,
            event_publisher=mock_publisher,
        )

        assert worker._provider_router is router
        assert worker.rate_limiter is mock_limiter
        assert worker._retry_strategy is mock_strategy
        assert worker._event_publisher is mock_publisher

    def test_init_metrics(self) -> None:
        """Metric counters start at zero."""
        worker = OutboxWorker(provider_router=_make_router())
        assert worker.metrics == {
            "messages_processed": 0,
            "messages_sent": 0,
            "messages_failed": 0,
            "messages_retried": 0,
        }

    def test_shared_shutdown_event(self) -> None:
        """A caller-provided shutdown event is used instead of a private one."""
        event = asyncio.Event()
        worker = OutboxWorker(provider_router=_make_router(), shutdown_event=event)

        assert worker.is_running is True
        event.set()
        assert worker.is_running is False


class TestBuildPendingQuery:
    """SQL compilation contract; this is the multi-pod safety net."""

    def test_compiled_sql_contains_for_update_skip_locked(self) -> None:
        """Query compiles with ``FOR UPDATE SKIP LOCKED`` clauses."""
        stmt = OutboxWorker._build_pending_query(limit=1)
        compiled = stmt.compile(dialect=postgresql.dialect())
        sql = str(compiled).upper()

        assert "FOR UPDATE" in sql, f"Missing FOR UPDATE in:\n{sql}"
        assert "SKIP LOCKED" in sql, f"Missing SKIP LOCKED in:\n{sql}"

    def test_compiled_sql_filters_pending_and_retrying(self) -> None:
        """Query filters by the same predicate the partial index covers."""
        stmt = OutboxWorker._build_pending_query(limit=1)
        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

        assert "STATUS IN" in sql.upper() or "status IN" in sql
        assert "'pending'" in sql
        assert "'retrying'" in sql

    def test_compiled_sql_skips_rows_with_a_future_retry_at(self) -> None:
        """A deferred row leaves the runnable set until its ``retry_at`` elapses."""
        stmt = OutboxWorker._build_pending_query(limit=1)
        sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        normalised = " ".join(sql.split())

        column = "notification_schema.messages.retry_at"
        assert f"{column} IS NULL OR {column} <= now()" in normalised

    def test_compiled_sql_orders_by_priority_then_created_at(self) -> None:
        """High-priority messages drain first, FIFO within priority."""
        stmt = OutboxWorker._build_pending_query(limit=5)
        sql = str(stmt.compile(dialect=postgresql.dialect()))

        # Matches the partial index ``ix_messages_queue (priority DESC, created_at)``.
        assert "priority DESC" in sql
        assert "created_at" in sql

    def test_limit_is_parameterised(self) -> None:
        """``limit`` is honoured; production calls always pass 1."""
        stmt = OutboxWorker._build_pending_query(limit=7)
        compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        assert "LIMIT 7" in str(compiled)


class TestCooperativeShutdown:
    """``asyncio.Event``-based shutdown."""

    @pytest.mark.asyncio
    async def test_stop_flips_is_running(self) -> None:
        """``stop()`` flips ``is_running`` without raising."""
        worker = OutboxWorker(provider_router=_make_router())
        assert worker.is_running
        worker.stop()
        assert not worker.is_running

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        """Calling ``stop()`` twice does not raise."""
        worker = OutboxWorker(provider_router=_make_router())
        worker.stop()
        worker.stop()
        assert not worker.is_running

    @pytest.mark.asyncio
    async def test_wait_or_shutdown_returns_true_when_already_set(self) -> None:
        """The wait helper returns immediately when shutdown is already set."""
        worker = OutboxWorker(provider_router=_make_router())
        worker.stop()
        # Large inner timeout, small outer timeout: returns immediately or fails fast.
        result = await asyncio.wait_for(worker._wait_or_shutdown(seconds=10.0), timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_or_shutdown_returns_false_on_timeout(self) -> None:
        """The wait helper returns False when its timeout expires."""
        worker = OutboxWorker(provider_router=_make_router())
        wait = AsyncMock(side_effect=TimeoutError)
        with patch.object(worker._shutdown, "wait", wait):
            result = await worker._wait_or_shutdown(seconds=10.0)
        assert result is False
        wait.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_wait_or_shutdown_returns_true_when_set_during_wait(self) -> None:
        """If shutdown fires mid-wait, the helper returns True."""
        worker = OutboxWorker(provider_router=_make_router())
        asyncio.get_running_loop().call_soon(worker.stop)

        result = await worker._wait_or_shutdown(seconds=1.0)

        assert result is True

    @pytest.mark.asyncio
    async def test_poll_loop_exits_promptly_when_stopped(self) -> None:
        """``start()`` returns after ``stop()`` without raising ``CancelledError``."""
        worker = OutboxWorker(provider_router=_make_router())

        # No-op drain isolates the loop wait logic.
        with patch.object(worker, "_drain_batch", new=AsyncMock(return_value=None)):
            worker.stop()
            await asyncio.wait_for(worker.start(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_poll_loop_does_not_cancel_in_flight_drain(self) -> None:
        """In-flight drain completes even after stop() fires."""
        worker = OutboxWorker(provider_router=_make_router())
        drain_started = asyncio.Event()
        release_drain = asyncio.Event()
        drain_finished = asyncio.Event()

        async def _in_flight_drain() -> None:
            drain_started.set()
            await release_drain.wait()
            drain_finished.set()

        with patch.object(worker, "_drain_batch", side_effect=_in_flight_drain):
            async with asyncio.TaskGroup() as tg:
                worker_task = tg.create_task(worker.start())
                await drain_started.wait()
                worker.stop()
                assert not drain_finished.is_set()
                release_drain.set()

        assert worker_task.result() is None
        assert drain_finished.is_set(), "Drain must finish before the loop exits"


class TestHandleMessageSuccess:
    """``_handle_message_success`` post-conditions."""

    @pytest.fixture
    def mock_publisher(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def worker(self, mock_publisher: AsyncMock) -> OutboxWorker:
        return OutboxWorker(provider_router=_make_router(), event_publisher=mock_publisher)

    @pytest.fixture
    def sent_message(self) -> MagicMock:
        msg = MagicMock(spec=Message)
        msg.id = uuid4()
        return msg

    @pytest.mark.asyncio
    async def test_success_updates_message_status(
        self,
        worker: OutboxWorker,
        sent_message: MagicMock,
    ) -> None:
        """Success transitions the row to SENT and clears retry state."""
        mock_db = create_mock_session()
        mock_provider = MagicMock()
        mock_provider.name = "resend"
        result = ProviderResult(success=True, provider_msg_id="msg_123")

        await worker._handle_message_success(mock_db, sent_message, mock_provider, result)

        assert sent_message.status == MessageStatus.SENT
        assert sent_message.provider_msg_id == "msg_123"
        assert sent_message.retry_count == 0
        assert sent_message.last_error is None
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_increments_metric(self, worker: OutboxWorker, sent_message: MagicMock) -> None:
        """Each successful send bumps the ``messages_sent`` counter."""
        mock_db = create_mock_session()
        mock_provider = MagicMock()
        result = ProviderResult(success=True, provider_msg_id="msg_123")

        await worker._handle_message_success(mock_db, sent_message, mock_provider, result)

        assert worker.metrics["messages_sent"] == 1

    @pytest.mark.asyncio
    async def test_success_publishes_event_before_commit(
        self,
        worker: OutboxWorker,
        mock_publisher: AsyncMock,
        sent_message: MagicMock,
    ) -> None:
        """``publish_sent`` is awaited within the same transaction as commit."""
        mock_db = create_mock_session()
        mock_provider = MagicMock()
        result = ProviderResult(success=True, provider_msg_id="msg_123")

        await worker._handle_message_success(mock_db, sent_message, mock_provider, result)

        mock_publisher.publish_sent.assert_awaited_once_with(mock_db, sent_message)


class TestHandleMessageFailure:
    """``_handle_message_failure`` retry vs permanent paths."""

    @pytest.fixture
    def mock_publisher(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def mock_strategy(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def worker(self, mock_publisher: AsyncMock, mock_strategy: MagicMock) -> OutboxWorker:
        return OutboxWorker(
            provider_router=_make_router(),
            event_publisher=mock_publisher,
            retry_strategy=mock_strategy,
        )

    @pytest.fixture
    def failed_message(self) -> MagicMock:
        msg = MagicMock(spec=Message)
        msg.id = uuid4()
        msg.retry_count = 0
        return msg

    @pytest.mark.asyncio
    async def test_failure_with_retry(
        self,
        worker: OutboxWorker,
        mock_strategy: MagicMock,
        failed_message: MagicMock,
    ) -> None:
        """Retryable failure schedules a future ``retry_at``."""
        mock_db = create_mock_session()
        result = ProviderResult(success=False, error="Temporary error", retryable=True)

        retry_at = datetime.now(UTC)
        mock_strategy.should_retry.return_value = RetryDecision(
            should_retry=True,
            retry_at=retry_at,
            delay_seconds=30,
        )

        await worker._handle_message_failure(mock_db, failed_message, "resend", result)

        assert failed_message.status == MessageStatus.RETRYING
        assert failed_message.retry_at == retry_at
        assert worker.metrics["messages_retried"] == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_no_retry(
        self,
        worker: OutboxWorker,
        mock_publisher: AsyncMock,
        mock_strategy: MagicMock,
        failed_message: MagicMock,
    ) -> None:
        """Exhausted retries promote the row to FAILED + publish_failed."""
        mock_db = create_mock_session()
        result = ProviderResult(success=False, error="Permanent error", retryable=False)

        mock_strategy.should_retry.return_value = RetryDecision(
            should_retry=False,
            retry_at=None,
            delay_seconds=0,
        )

        await worker._handle_message_failure(mock_db, failed_message, "resend", result)

        assert failed_message.status == MessageStatus.FAILED
        assert failed_message.retry_at is None
        assert worker.metrics["messages_failed"] == 1
        mock_publisher.publish_failed.assert_awaited_once()


class TestSendMessage:
    """``_send_message`` dispatch contract."""

    @pytest.fixture
    def base_strategy(self) -> MagicMock:
        strategy = MagicMock()
        strategy.should_retry.return_value = RetryDecision(should_retry=False, retry_at=None, delay_seconds=0)
        return strategy

    @pytest.fixture
    def pending_message(self) -> MagicMock:
        return _make_message()

    @pytest.mark.asyncio
    async def test_delivered_marks_sent(
        self,
        base_strategy: MagicMock,
        pending_message: MagicMock,
    ) -> None:
        """DELIVERED verdict drives the row to SENT."""
        router = _make_router()
        worker = OutboxWorker(
            provider_router=router,
            retry_strategy=base_strategy,
            event_publisher=AsyncMock(),
        )
        mock_db = create_mock_session()

        await worker._send_message(mock_db, pending_message)

        assert pending_message.status == MessageStatus.SENT
        router.send.assert_awaited_once_with(pending_message)

    @pytest.mark.asyncio
    async def test_failed_marks_failed_when_not_retryable(
        self,
        base_strategy: MagicMock,
        pending_message: MagicMock,
    ) -> None:
        """FAILED + non-retryable promotes to FAILED."""
        router = _make_router(send=AsyncMock(return_value=_failed_outcome(retryable=False)))
        worker = OutboxWorker(
            provider_router=router,
            retry_strategy=base_strategy,
            event_publisher=AsyncMock(),
        )
        mock_db = create_mock_session()

        await worker._send_message(mock_db, pending_message)

        assert pending_message.status == MessageStatus.FAILED

    @pytest.mark.asyncio
    async def test_all_circuits_open_leaves_row_untouched(
        self,
        base_strategy: MagicMock,
        pending_message: MagicMock,
    ) -> None:
        """ALL_CIRCUITS_OPEN does not commit; lock released by context exit."""
        router = _make_router(send=AsyncMock(return_value=_all_open_outcome()))
        worker = OutboxWorker(
            provider_router=router,
            retry_strategy=base_strategy,
            event_publisher=AsyncMock(),
        )
        mock_db = create_mock_session()
        original_status = MessageStatus.PENDING
        pending_message.status = original_status

        progressed = await worker._send_message(mock_db, pending_message)

        assert progressed is False
        assert pending_message.status == original_status
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_retryable_failed_outcome_routes_to_failure_handler(
        self,
        base_strategy: MagicMock,
        pending_message: MagicMock,
    ) -> None:
        """Synthetic FAILED+retryable outcomes (e.g. provider raised) reach the failure handler."""
        synthetic = SendOutcome(
            verdict=SendVerdict.FAILED,
            provider=MagicMock(name="resend"),
            result=ProviderResult(success=False, error="network", retryable=True),
        )
        router = _make_router(send=AsyncMock(return_value=synthetic))
        worker = OutboxWorker(
            provider_router=router,
            retry_strategy=base_strategy,
            event_publisher=AsyncMock(),
        )
        mock_db = create_mock_session()

        await worker._send_message(mock_db, pending_message)

        # base_strategy.should_retry returns no-retry, so status should be FAILED.
        assert pending_message.status == MessageStatus.FAILED

    @pytest.mark.asyncio
    async def test_rate_limit_denied_skips_router(
        self,
        base_strategy: MagicMock,
        pending_message: MagicMock,
    ) -> None:
        """When the provider bucket denies, the router is not invoked."""
        router = _make_router()
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=False, retry_after=6.0)
        worker = OutboxWorker(
            provider_router=router,
            rate_limiter=limiter,
            retry_strategy=base_strategy,
        )
        mock_db = create_mock_session()

        progressed = await worker._send_message(mock_db, pending_message)

        assert progressed is True
        router.send.assert_not_called()
        assert pending_message.retry_at > datetime.now(UTC)


class TestFrequencyCap:
    """Per-user cap sits between the claim and the provider."""

    @staticmethod
    def _checker(*, allowed: bool, retry_after: float | None = 45.0) -> MagicMock:
        checker = MagicMock(spec=FrequencyChecker)
        checker.check = AsyncMock(
            return_value=RateLimitResult(
                allowed=allowed,
                remaining=0 if not allowed else 1,
                reset_at=datetime.now(UTC).timestamp() + 60,
                retry_after=None if allowed else retry_after,
            ),
        )
        return checker

    @pytest.mark.asyncio
    async def test_capped_user_never_reaches_a_provider(self) -> None:
        """A throttled message costs no provider quota."""
        router = _make_router()
        worker = OutboxWorker(provider_router=router, frequency_checker=self._checker(allowed=False))
        message = _make_message(user_id=uuid4())
        message.status = MessageStatus.PENDING
        mock_db = create_mock_session()

        progressed = await worker._send_message(mock_db, message)

        assert progressed is True
        router.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_cap_denial_charges_no_provider_token(self) -> None:
        """The recipient cap is evaluated before any provider quota is spent."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=True, retry_after=None)
        worker = OutboxWorker(
            provider_router=_make_router(),
            rate_limiter=limiter,
            frequency_checker=self._checker(allowed=False),
        )
        message = _make_message(user_id=uuid4())
        message.status = MessageStatus.PENDING

        await worker._send_message(create_mock_session(), message)

        limiter.check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_throttled_row_is_deferred_by_the_limiters_retry_after(self) -> None:
        """The row keeps its status and becomes eligible when tokens refill."""
        worker = OutboxWorker(
            provider_router=_make_router(),
            frequency_checker=self._checker(allowed=False, retry_after=45.0),
        )
        message = _make_message(user_id=uuid4())
        message.status = MessageStatus.PENDING
        message.retry_count = 3
        mock_db = create_mock_session()

        before = datetime.now(UTC)
        await worker._send_message(mock_db, message)

        assert message.status == MessageStatus.PENDING
        assert message.retry_count == 3
        # Deferred by the bucket's own estimate, not a fixed poll-interval delay.
        assert timedelta(seconds=44) <= message.retry_at - before <= timedelta(seconds=46)
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_throttle_defer_has_a_floor(self) -> None:
        """A sub-second retry_after would be past by the next claim and reselect the row."""
        worker = OutboxWorker(
            provider_router=_make_router(),
            frequency_checker=self._checker(allowed=False, retry_after=0.002),
        )
        message = _make_message(user_id=uuid4())
        message.status = MessageStatus.PENDING

        before = datetime.now(UTC)
        await worker._send_message(create_mock_session(), message)

        assert message.retry_at - before >= timedelta(seconds=MIN_THROTTLE_DEFER_SECONDS)

    @pytest.mark.asyncio
    async def test_user_below_the_cap_is_dispatched(self) -> None:
        """Admitting the send routes it and charges the user exactly once."""
        router = _make_router()
        checker = self._checker(allowed=True)
        worker = OutboxWorker(
            provider_router=router,
            retry_strategy=MagicMock(spec=RetryStrategy),
            event_publisher=AsyncMock(),
            frequency_checker=checker,
        )
        user_id = uuid4()
        message = _make_message(user_id=user_id)
        mock_db = create_mock_session()

        progressed = await worker._send_message(mock_db, message)

        assert progressed is True
        assert message.status == MessageStatus.SENT
        router.send.assert_awaited_once_with(message)
        checker.check.assert_awaited_once_with(user_id)

    @pytest.mark.asyncio
    async def test_no_checker_leaves_dispatch_untouched(self) -> None:
        """With the cap disabled the worker behaves exactly as before."""
        router = _make_router()
        worker = OutboxWorker(provider_router=router, event_publisher=AsyncMock())

        await worker._send_message(create_mock_session(), _make_message(user_id=uuid4()))

        router.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_message_without_a_user_is_not_capped(self) -> None:
        """A system message with no recipient id has no bucket to charge."""
        router = _make_router()
        checker = self._checker(allowed=False)
        worker = OutboxWorker(
            provider_router=router,
            event_publisher=AsyncMock(),
            frequency_checker=checker,
        )

        await worker._send_message(create_mock_session(), _make_message(user_id=None))

        checker.check.assert_not_called()
        router.send.assert_awaited_once()


class TestPreSendExpiry:
    """TTL guard between claiming a row and dispatching it."""

    @pytest.mark.asyncio
    async def test_expired_message_is_cancelled_without_a_send(self) -> None:
        """A row whose TTL elapsed after the claim is never delivered."""
        router = _make_router()
        publisher = AsyncMock(spec=NotificationEventPublisher)
        worker = OutboxWorker(provider_router=router, event_publisher=publisher)
        message = _make_message(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        mock_db = create_mock_session()

        progressed = await worker._send_message(mock_db, message)

        assert progressed is True
        assert message.status == MessageStatus.CANCELLED
        assert message.last_error == EXPIRED_ERROR
        assert message.retry_at is None
        mock_db.commit.assert_awaited_once()
        router.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_expiry_between_claim_and_send_emits_one_lifecycle_event(self) -> None:
        """The worker's own expiry path is as observable as the sweep's."""
        publisher = AsyncMock(spec=NotificationEventPublisher)
        worker = OutboxWorker(provider_router=_make_router(), event_publisher=publisher)
        message = _make_message(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        mock_db = create_mock_session()

        await worker._send_message(mock_db, message)

        publisher.publish_failed.assert_awaited_once_with(mock_db, message)

    @pytest.mark.asyncio
    async def test_message_still_within_its_ttl_is_sent(self) -> None:
        """An unexpired row takes the normal dispatch path."""
        router = _make_router()
        worker = OutboxWorker(provider_router=router, event_publisher=AsyncMock())
        message = _make_message(expires_at=datetime.now(UTC) + timedelta(hours=1))

        await worker._send_message(create_mock_session(), message)

        assert message.status == MessageStatus.SENT
        router.send.assert_awaited_once_with(message)

    @pytest.mark.asyncio
    async def test_message_without_an_expiry_is_never_cancelled(self) -> None:
        """``expires_at`` NULL means no TTL, not an elapsed one."""
        router = _make_router()
        worker = OutboxWorker(provider_router=router, event_publisher=AsyncMock())
        message = _make_message(expires_at=None)

        await worker._send_message(create_mock_session(), message)

        assert message.status == MessageStatus.SENT
        router.send.assert_awaited_once_with(message)


class TestCheckRateLimits:
    """Provider-bucket branch coverage. ``None`` means admitted."""

    @pytest.mark.asyncio
    async def test_no_limiter_admits(self) -> None:
        """Without a limiter, every message is allowed."""
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=None)
        msg = MagicMock(spec=Message)
        msg.provider_name = "resend"

        assert await worker._check_rate_limits(msg) is None

    @pytest.mark.asyncio
    async def test_default_provider_is_rate_limited(self) -> None:
        """A message without an override still uses the configured provider bucket."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=False, retry_after=6.0)
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=limiter)
        msg = MagicMock(spec=Message)
        msg.provider_name = None
        msg.channel.to_proto.return_value = NotificationChannel.EMAIL

        with patch(
            "notification_service.services.outbox.worker.get_default_provider_name",
            return_value="resend",
        ):
            retry_after = await worker._check_rate_limits(msg)

        assert retry_after == 6.0
        limiter.check.assert_awaited_once_with("provider:resend")

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self) -> None:
        """Limiter ``allowed=True`` reports no deferral."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=True, retry_after=None)
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=limiter)
        msg = MagicMock(spec=Message)
        msg.provider_name = "resend"

        assert await worker._check_rate_limits(msg) is None

    @pytest.mark.asyncio
    async def test_rate_limit_denied_reports_the_buckets_estimate(self) -> None:
        """Limiter ``allowed=False`` surfaces the seconds until a token returns."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=False, retry_after=12.5)
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=limiter)
        msg = MagicMock(spec=Message)
        msg.provider_name = "resend"

        assert await worker._check_rate_limits(msg) == 12.5


class TestOutcomeInvariants:
    """The match-case dispatch enforces structural invariants on SendOutcome."""

    @pytest.mark.asyncio
    async def test_delivered_with_missing_provider_raises(self) -> None:
        """A DELIVERED outcome must carry a provider; otherwise the worker raises."""
        bad_outcome = SendOutcome(
            verdict=SendVerdict.DELIVERED,
            provider=None,
            result=ProviderResult(success=True),
        )
        worker = OutboxWorker(provider_router=_make_router())
        with pytest.raises(RuntimeError, match="DELIVERED outcome"):
            await worker._handle_delivered(create_mock_session(), _make_message(), bad_outcome)

    @pytest.mark.asyncio
    async def test_failed_with_missing_result_raises(self) -> None:
        """A FAILED outcome must carry a result; otherwise the worker raises."""
        bad_outcome = SendOutcome(verdict=SendVerdict.FAILED, provider=None, result=None)
        worker = OutboxWorker(provider_router=_make_router())
        with pytest.raises(RuntimeError, match="FAILED outcome"):
            await worker._handle_failed(create_mock_session(), _make_message(), bad_outcome)


class TestPollLoopErrorRecovery:
    """The poll loop must survive structural errors."""

    @pytest.mark.asyncio
    async def test_loop_continues_after_drain_exception(self) -> None:
        """Drain raising once does not exit the loop; backoff is applied."""
        worker = OutboxWorker(provider_router=_make_router())
        call_count = 0

        async def _flaky_drain() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "transient"
                raise RuntimeError(msg)
            worker.stop()

        # Short-circuit poll/error backoff so the test runs fast.
        with (
            patch.object(worker, "_drain_batch", side_effect=_flaky_drain),
            patch.object(worker, "_wait_or_shutdown", new=AsyncMock(return_value=False)),
        ):
            await asyncio.wait_for(worker.start(), timeout=2.0)

        assert call_count == 2


class TestDrainBatch:
    """End-to-end ``_drain_batch`` semantics with mocked DB."""

    @pytest.mark.asyncio
    async def test_drains_messages_from_query(self) -> None:
        """Each iteration claims one row and routes it through the router."""
        worker = OutboxWorker(provider_router=_make_router())
        messages: Iterable[MagicMock] = [_make_message(), _make_message()]
        iter_messages = iter(messages)

        mock_db = create_mock_session()

        def _execute_result(_stmt: object) -> MagicMock:
            result = MagicMock()
            try:
                next_msg = next(iter_messages)
            except StopIteration:
                next_msg = None
            result.scalars.return_value.first.return_value = next_msg
            return result

        mock_db.execute = AsyncMock(side_effect=_execute_result)

        # batch_size > queue length exercises the StopIteration early-return path.
        with (
            patch(
                "notification_service.services.outbox.worker.db_session",
                return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_db), __aexit__=AsyncMock()),
            ),
            patch.object(worker, "_send_message", new_callable=AsyncMock, return_value=True) as mock_send,
            patch("notification_service.services.outbox.worker.settings") as mock_settings,
        ):
            mock_settings.outbox.batch_size = 10
            mock_settings.database = MagicMock()
            await worker._drain_batch()

        assert mock_send.await_count == 2
        assert worker.metrics["messages_processed"] == 2

    @pytest.mark.asyncio
    async def test_deferred_head_stops_current_cycle(self) -> None:
        """A deferred head is attempted once, then left for a later poll cycle."""
        worker = OutboxWorker(provider_router=_make_router())
        message = _make_message()
        mock_db = create_mock_session()
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = message
        mock_db.execute = AsyncMock(return_value=execute_result)

        with (
            patch(
                "notification_service.services.outbox.worker.db_session",
                return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_db), __aexit__=AsyncMock()),
            ),
            patch.object(worker, "_send_message", new_callable=AsyncMock, return_value=False) as mock_send,
            patch("notification_service.services.outbox.worker.settings") as mock_settings,
        ):
            mock_settings.outbox.batch_size = 10
            mock_settings.database = MagicMock()
            await worker._drain_batch()

        mock_send.assert_awaited_once_with(mock_db, message)
        assert mock_db.execute.await_count == 1
        assert worker.metrics["messages_processed"] == 0

    @pytest.mark.asyncio
    async def test_returns_early_when_shutdown_set(self) -> None:
        """A shutdown signal between iterations short-circuits the batch."""
        worker = OutboxWorker(provider_router=_make_router())
        worker.stop()

        with patch(
            "notification_service.services.outbox.worker.db_session",
            return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()),
        ) as mock_session_cm:
            await worker._drain_batch()

        mock_session_cm.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_exception_marks_retrying(self) -> None:
        """Defensive: an unhandled exception inside send still rewrites status."""
        worker = OutboxWorker(provider_router=_make_router())
        message = _make_message()

        mock_db = create_mock_session()
        execute_result = MagicMock()
        execute_result.scalars.return_value.first.return_value = message
        mock_db.execute = AsyncMock(return_value=execute_result)

        with (
            patch(
                "notification_service.services.outbox.worker.db_session",
                return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_db), __aexit__=AsyncMock()),
            ),
            patch.object(worker, "_send_message", side_effect=RuntimeError("kaboom")),
            patch("notification_service.services.outbox.worker.settings") as mock_settings,
        ):
            mock_settings.outbox.batch_size = 1
            mock_settings.database = MagicMock()
            await worker._drain_batch()

        assert message.status == MessageStatus.RETRYING
        mock_db.commit.assert_awaited()


class TestGetMetrics:
    """Metrics snapshot contract."""

    def test_get_metrics_returns_copy(self) -> None:
        """Mutating the returned dict must not affect the worker."""
        worker = OutboxWorker(provider_router=_make_router())
        worker.metrics["messages_sent"] = 5
        snapshot = worker.get_metrics()

        snapshot["messages_sent"] = 999
        assert worker.metrics["messages_sent"] == 5


class TestThrottleLiveness:
    """A capped recipient must not starve the rest of the queue."""

    @staticmethod
    def _runnable(queue: list[MagicMock]) -> MagicMock:
        """Claim the first row the queue predicate would actually select."""
        now = datetime.now(UTC)
        result = MagicMock()
        eligible = [
            msg
            for msg in queue
            if msg.status in (MessageStatus.PENDING, MessageStatus.RETRYING)
            and (msg.retry_at is None or msg.retry_at <= now)
        ]
        result.scalars.return_value.first.return_value = eligible[0] if eligible else None
        return result

    @pytest.mark.asyncio
    async def test_capped_user_does_not_block_another_users_row(self) -> None:
        """The batch continues past a throttled head instead of ending on it."""
        capped_user = uuid4()
        capped = _make_message(user_id=capped_user)
        capped.status = MessageStatus.PENDING
        capped.retry_at = None
        other = _make_message(user_id=uuid4())
        other.status = MessageStatus.PENDING
        other.retry_at = None
        queue = [capped, other]

        async def _check(user_id: UUID) -> RateLimitResult:
            allowed = user_id != capped_user
            return RateLimitResult(
                allowed=allowed,
                remaining=0,
                reset_at=datetime.now(UTC).timestamp() + 60,
                retry_after=None if allowed else 30.0,
            )

        checker = MagicMock(spec=FrequencyChecker)
        checker.check = AsyncMock(side_effect=_check)

        mock_db = create_mock_session()
        mock_db.execute = AsyncMock(side_effect=lambda _stmt: self._runnable(queue))
        router = _make_router()
        worker = OutboxWorker(
            provider_router=router,
            frequency_checker=checker,
            event_publisher=AsyncMock(),
        )

        with (
            patch(
                "notification_service.services.outbox.worker.db_session",
                return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_db), __aexit__=AsyncMock()),
            ),
            patch("notification_service.services.outbox.worker.settings") as mock_settings,
        ):
            mock_settings.outbox.batch_size = 10
            mock_settings.database = MagicMock()
            await worker._drain_batch()

        router.send.assert_awaited_once_with(other)
        assert other.status == MessageStatus.SENT
        assert capped.status == MessageStatus.PENDING
        assert capped.retry_at > datetime.now(UTC)


class TestCapFailsClosed:
    """The inbox bound has to hold when its backend is the thing that broke."""

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_admit_a_send(self) -> None:
        """An unreachable bucket defers the row rather than waving it through."""
        cache = MagicMock()
        cache.eval_script = AsyncMock(side_effect=RedisError("redis unreachable"))
        limiter = create_token_bucket_limiter(
            cache=cache,
            requests=3,
            window_seconds=60,
            failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
        )
        router = _make_router()
        worker = OutboxWorker(
            provider_router=router,
            frequency_checker=FrequencyChecker(limiter, max_per_window=3, window_seconds=60),
            event_publisher=AsyncMock(),
        )
        message = _make_message(user_id=uuid4())
        message.status = MessageStatus.PENDING
        mock_db = create_mock_session()

        progressed = await worker._send_message(mock_db, message)

        assert progressed is True
        router.send.assert_not_called()
        assert message.status == MessageStatus.PENDING
        assert message.retry_at > datetime.now(UTC)
        mock_db.commit.assert_awaited_once()

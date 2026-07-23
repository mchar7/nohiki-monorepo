"""Unit tests for the OutboxWorker.

Exercises three things the worker is responsible for: the SKIP LOCKED claim
query, cooperative shutdown via :class:`asyncio.Event`, and the
``SendOutcome`` -> DB transition mapping. The :class:`ProviderRouter` and DB
session are both mocked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_db_utils.testing import create_mock_session
from notification_service.core.providers import ProviderResult
from notification_service.db.models import Message, MessageStatus
from notification_service.services.outbox import OutboxWorker
from notification_service.services.outbox.event_publisher import NotificationEventPublisher
from notification_service.services.outbox.provider_router import ProviderRouter, SendOutcome, SendVerdict
from notification_service.services.outbox.retry_strategy import RetryDecision, RetryStrategy
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


def _make_message() -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.id = uuid4()
    msg.retry_count = 0
    msg.provider_name = "resend"
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
        """When the rate limiter denies, the router is not invoked."""
        router = _make_router()
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=False)
        worker = OutboxWorker(
            provider_router=router,
            rate_limiter=limiter,
            retry_strategy=base_strategy,
        )
        mock_db = create_mock_session()

        progressed = await worker._send_message(mock_db, pending_message)

        assert progressed is False
        router.send.assert_not_called()


class TestCheckRateLimits:
    """Rate-limit branch coverage."""

    @pytest.mark.asyncio
    async def test_no_limiter_returns_true(self) -> None:
        """Without a limiter, every message is allowed."""
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=None)
        msg = MagicMock(spec=Message)
        msg.provider_name = "resend"

        assert await worker._check_rate_limits(msg) is True

    @pytest.mark.asyncio
    async def test_default_provider_is_rate_limited(self) -> None:
        """A message without an override still uses the configured provider bucket."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=False)
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=limiter)
        msg = MagicMock(spec=Message)
        msg.provider_name = None
        msg.channel.to_proto.return_value = NotificationChannel.EMAIL

        with patch(
            "notification_service.services.outbox.worker.get_default_provider_name",
            return_value="resend",
        ):
            allowed = await worker._check_rate_limits(msg)

        assert allowed is False
        limiter.check.assert_awaited_once_with("provider:resend")

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(self) -> None:
        """Limiter ``allowed=True`` returns True."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=True)
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=limiter)
        msg = MagicMock(spec=Message)
        msg.provider_name = "resend"

        assert await worker._check_rate_limits(msg) is True

    @pytest.mark.asyncio
    async def test_rate_limit_denied(self) -> None:
        """Limiter ``allowed=False`` returns False."""
        limiter = AsyncMock()
        limiter.check.return_value = MagicMock(allowed=False)
        worker = OutboxWorker(provider_router=_make_router(), rate_limiter=limiter)
        msg = MagicMock(spec=Message)
        msg.provider_name = "resend"

        assert await worker._check_rate_limits(msg) is False


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

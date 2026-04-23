"""Outbox worker for background message processing.

Multi-pod safety has two parts:

1. ``SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`` claims one row under a
   row-level lock and silently passes over rows another worker already holds.
2. Each message gets its own transaction. The lock is held from SELECT through
   the status update and outbox write, then released at commit. Workers never
   share a transaction across messages, so committing one row never frees
   another worker's lock.

Shutdown is cooperative. ``stop()`` sets an :class:`asyncio.Event` that the
poll loop checks between messages and during sleeps. We never task-cancel the
worker, which means a ``CancelledError`` cannot land between
``provider.send()`` succeeding and ``db.commit()`` persisting that success.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nohiki_db_utils import db_session
from nohiki_observability import get_logger
from sqlalchemy import Select, func, select

from notification_service.core.config import settings
from notification_service.core.providers import BaseProvider, ProviderResult, get_default_provider_name
from notification_service.db.models import Message, MessageStatus
from notification_service.services.outbox.event_publisher import NotificationEventPublisher
from notification_service.services.outbox.provider_router import ProviderRouter, SendOutcome, SendVerdict
from notification_service.services.outbox.retry_strategy import RetryStrategy

if TYPE_CHECKING:
    from nohiki_redis_utils import RateLimiter
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class OutboxWorker:
    """Polls the messages table and dispatches sends through a ProviderRouter.

    Designed to run as N replicas against the same database with no
    coordination beyond Postgres row locks. Retries are scheduled by
    :class:`RetryStrategy`.
    """

    def __init__(
        self,
        provider_router: ProviderRouter,
        *,
        rate_limiter: RateLimiter | None = None,
        retry_strategy: RetryStrategy | None = None,
        event_publisher: NotificationEventPublisher | None = None,
        shutdown_event: asyncio.Event | None = None,
    ) -> None:
        """Build a worker.

        Args:
            provider_router: Owns provider selection and breaker state.
                Required.
            rate_limiter: Optional limiter applied per provider name before
                the router runs.
            retry_strategy: Retry scheduler. Defaults to a new
                :class:`RetryStrategy`.
            event_publisher: Lifecycle event publisher. Defaults to a new
                :class:`NotificationEventPublisher`.
            shutdown_event: Optional shared shutdown signal. Pass the same
                event used by the lifespan handler so one ``set()`` stops
                both. A private event is created if omitted.

        """
        self._provider_router = provider_router
        self.rate_limiter = rate_limiter
        self._retry_strategy = retry_strategy or RetryStrategy()
        self._event_publisher = event_publisher or NotificationEventPublisher()
        self._shutdown = shutdown_event or asyncio.Event()
        self._init_metrics()

    @property
    def is_running(self) -> bool:
        """``True`` until shutdown is signalled. Read-only view of liveness."""
        return not self._shutdown.is_set()

    def _init_metrics(self) -> None:
        self.metrics: dict[str, int] = {
            "messages_processed": 0,
            "messages_sent": 0,
            "messages_failed": 0,
            "messages_retried": 0,
        }

    async def start(self) -> None:
        """Run the poll loop until :meth:`stop` is called.

        Not safe to call twice on the same instance.
        """
        logger.info(
            "Starting outbox worker",
            poll_interval_sec=settings.outbox.poll_interval_sec,
            batch_size=settings.outbox.batch_size,
        )
        await self._poll_loop()
        logger.info("Outbox worker exited cleanly")

    def stop(self) -> None:
        """Ask the worker to stop after the current message.

        Idempotent and non-blocking. ``await`` the original ``start()`` task
        to see the actual exit.
        """
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        logger.info("Outbox worker shutdown signalled")

    async def _poll_loop(self) -> None:
        """Drain the queue until shutdown is signalled."""
        while not self._shutdown.is_set():
            try:
                await self._drain_batch()
            except Exception:
                # Persistent failures (DB outage, schema drift) would otherwise
                # spin the loop with no work done. Back off and re-check.
                logger.exception("Outbox worker poll cycle failed; backing off")
                await self._wait_or_shutdown(settings.outbox.error_backoff_seconds)
                continue

            await self._wait_or_shutdown(settings.outbox.poll_interval_sec)

    async def _wait_or_shutdown(self, seconds: float) -> bool:
        """Wait for shutdown or for ``seconds``, whichever comes first.

        Args:
            seconds: Maximum seconds to wait.

        Returns:
            ``True`` if shutdown was signalled during the wait, ``False`` on
            timeout.

        """
        try:
            await asyncio.wait_for(self._shutdown.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

    async def _drain_batch(self) -> None:
        """Process up to ``batch_size`` messages, each in its own transaction.

        Every iteration opens a fresh session, claims one row with
        ``SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1``, processes it, and
        commits. One row per transaction keeps lock-hold time short and
        prevents a commit on one message from releasing locks on siblings.

        Exits early if shutdown fires between messages.
        """
        for _ in range(settings.outbox.batch_size):
            if self._shutdown.is_set():
                return

            async with db_session(settings.database) as db:
                stmt = self._build_pending_query(limit=1)
                result = await db.execute(stmt)
                message = result.scalars().first()
                if message is None:
                    return  # Queue empty for this cycle.

                try:
                    progressed = await self._send_message(db, message)
                except Exception:
                    logger.exception("Unhandled error processing message", message_id=str(message.id))
                    message.retry_count += 1
                    decision = self._retry_strategy.should_retry(message.retry_count, retryable=True)
                    if decision.should_retry:
                        message.status = MessageStatus.RETRYING
                        message.retry_at = decision.retry_at
                    else:
                        message.status = MessageStatus.FAILED
                        message.retry_at = None
                        await self._event_publisher.publish_failed(db, message)
                    await db.commit()
                    return
                if not progressed:
                    return
                self.metrics["messages_processed"] += 1

    @staticmethod
    def _build_pending_query(limit: int) -> Select[tuple[Message]]:
        """Build the pending-message claim query.

        The predicate matches the partial index ``ix_messages_queue`` exactly,
        so ``FOR UPDATE SKIP LOCKED`` adds no extra scan cost.

        Args:
            limit: Maximum rows per statement. Production callers pass ``1``;
                the parameter exists so tests can vary it without hard-coding
                a magic number.

        Returns:
            A SQLAlchemy ``Select`` with ``FOR UPDATE SKIP LOCKED`` applied.

        """
        return (
            select(Message)
            .where(
                Message.status.in_([MessageStatus.PENDING, MessageStatus.RETRYING]),
                (Message.scheduled_at.is_(None)) | (Message.scheduled_at <= func.now()),
                (Message.retry_at.is_(None)) | (Message.retry_at <= func.now()),
            )
            .order_by(Message.priority.desc(), Message.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

    async def _send_message(self, db: AsyncSession, message: Message) -> bool:
        """Dispatch one claimed message and persist the outcome.

        Args:
            db: Session holding the row's lock.
            message: The locked row.

        """
        if not await self._check_rate_limits(message):
            logger.debug("Rate limit exceeded; deferring message", message_id=str(message.id))
            return False

        outcome = await self._provider_router.send(message)

        match outcome.verdict:
            case SendVerdict.DELIVERED:
                await self._handle_delivered(db, message, outcome)
                return True
            case SendVerdict.FAILED:
                await self._handle_failed(db, message, outcome)
                return True
            case SendVerdict.ALL_CIRCUITS_OPEN:
                # No commit. The session rolls back, the lock releases, and a
                # later poll picks the row up once a breaker has recovered.
                logger.info(
                    "All provider circuits open; leaving message for next cycle",
                    message_id=str(message.id),
                )
                return False

    async def _handle_delivered(self, db: AsyncSession, message: Message, outcome: SendOutcome) -> None:
        """Persist a successful delivery and emit the lifecycle event."""
        if outcome.provider is None or outcome.result is None:
            msg = "DELIVERED outcome must carry both provider and result"
            raise RuntimeError(msg)
        await self._handle_message_success(db, message, outcome.provider, outcome.result)

    async def _handle_failed(self, db: AsyncSession, message: Message, outcome: SendOutcome) -> None:
        """Persist a responded failure, deciding retry vs permanent."""
        if outcome.result is None:
            msg = "FAILED outcome must carry a result"
            raise RuntimeError(msg)
        # Router-synthesised "provider not found" failures have no provider.
        # Use the message's declared name for logging.
        provider_name = (
            outcome.provider.name if outcome.provider is not None else (message.provider_name or "<unknown>")
        )
        await self._handle_message_failure(db, message, provider_name, outcome.result)

    async def _handle_message_success(
        self,
        db: AsyncSession,
        message: Message,
        provider: BaseProvider,
        result: ProviderResult,
    ) -> None:
        """Commit a successful send and write ``NotificationSent`` to the outbox."""
        message.status = MessageStatus.SENT
        message.provider_msg_id = result.provider_msg_id
        message.sent_at = func.now()
        message.retry_count = 0
        message.last_error = None

        # Outbox row and status update must commit together.
        await self._event_publisher.publish_sent(db, message)

        await db.commit()
        self.metrics["messages_sent"] += 1

        logger.info(
            "Message sent",
            message_id=str(message.id),
            provider=provider.name,
            provider_msg_id=result.provider_msg_id,
        )

    async def _handle_message_failure(
        self,
        db: AsyncSession,
        message: Message,
        provider_name: str,
        result: ProviderResult,
    ) -> None:
        """Handle a responded provider failure (retry-eligible or permanent)."""
        message.retry_count += 1
        message.last_error = result.error

        decision = self._retry_strategy.should_retry(
            message.retry_count,
            retryable=result.retryable,
            retry_after_seconds=result.retry_after_seconds,
        )

        if decision.should_retry:
            message.retry_at = decision.retry_at
            message.status = MessageStatus.RETRYING

            await db.commit()
            self.metrics["messages_retried"] += 1

            logger.warning(
                "Message failed, will retry",
                message_id=str(message.id),
                provider=provider_name,
                retry_count=message.retry_count,
                retry_at=message.retry_at,
            )
        else:
            message.status = MessageStatus.FAILED
            message.retry_at = None

            # Outbox row and status update must commit together.
            await self._event_publisher.publish_failed(db, message)

            await db.commit()
            self.metrics["messages_failed"] += 1

            logger.error(
                "Message permanently failed",
                message_id=str(message.id),
                provider=provider_name,
                retry_count=message.retry_count,
            )

    async def _check_rate_limits(self, message: Message) -> bool:
        """Check the per-provider rate limiter, if any.

        Args:
            message: Message about to be dispatched.

        Returns:
            ``True`` when no limiter is configured or the limiter allows the
            provider bucket. ``False`` only when the limiter explicitly denies.

        """
        if not self.rate_limiter:
            return True

        provider_name = message.provider_name or get_default_provider_name(message.channel.to_proto())
        if provider_name is None:
            return True

        rate_limit_key = f"provider:{provider_name}"
        check_result = await self.rate_limiter.check(rate_limit_key)
        return check_result.allowed

    def get_metrics(self) -> dict[str, Any]:
        """Return a defensive copy of in-process metrics counters."""
        return self.metrics.copy()

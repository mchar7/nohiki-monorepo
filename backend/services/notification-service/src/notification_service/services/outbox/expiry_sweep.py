"""Periodic sweep that cancels messages past their TTL.

A queued notification that is a day stale is worse than none, and unswept rows
keep widening the partial queue index that every poll cycle walks.

Expiry is a delivery outcome, not a quiet cleanup: a row can reach its TTL while
still eligible to send (a cap deferral, a fail-closed limiter outage, sustained
higher-priority traffic), so every cancellation writes a ``NotificationFailed``
outbox row in the same transaction as the status change. Downstream consumers see
the loss instead of inferring it from a row that stopped moving.

Multi-pod safety reuses the worker's discipline rather than adding a second one:
the rows to cancel are chosen by ``SELECT ... FOR UPDATE SKIP LOCKED``, so a
second sweeping pod passes over rows this one holds and the outbox worker never
waits behind the sweep for a row it is mid-send on. The claimed batch is then
expired row by row under those locks and committed once, so a pass costs one
transaction rather than one per row.

Shutdown is the worker's shared :class:`asyncio.Event`: one ``set()`` stops the
poll loop and the sweep together.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from nohiki_observability import get_logger
from sqlalchemy import Select, func, select

from notification_service.db.models import Message, MessageStatus
from notification_service.services.outbox.event_publisher import NotificationEventPublisher

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)

EXPIRED_ERROR = "Message expired before dispatch (TTL exceeded)"

EXPIRABLE_STATUSES: Final[tuple[MessageStatus, ...]] = (
    MessageStatus.PENDING,
    MessageStatus.WAITING_FOR_RENDER,
    MessageStatus.RETRYING,
)
"""States from which a message is still awaiting a delivery attempt.

``PENDING`` and ``RETRYING`` are the worker's runnable set. ``WAITING_FOR_RENDER``
is stamped with an ``expires_at`` at creation like any other row, and a render
callback that never arrives leaves it parked forever unless the sweep claims it.
``SENT`` and ``CANCELLED`` are terminal by :attr:`Message.__transitions__`.
``FAILED`` is excluded deliberately: the worker only sets it once the retry
budget is spent, having already emitted its ``NotificationFailed``, so expiring
it would rewrite a reported permanent failure and emit a second event for the
same loss. Kept in lockstep with the ``ix_messages_expires_at`` predicate.
"""


async def expire_message(db: AsyncSession, message: Message, publisher: NotificationEventPublisher) -> None:
    """Cancel a locked row for TTL expiry and queue its lifecycle event.

    Does not commit: the outbox row and the status change must land in the
    caller's transaction together.

    Args:
        db: Session holding the row's lock.
        message: The row to expire.
        publisher: Lifecycle event publisher writing into ``db``.

    """
    message.status = MessageStatus.CANCELLED
    message.last_error = EXPIRED_ERROR
    message.retry_at = None
    await publisher.publish_failed(db, message)


class MessageExpirySweep:
    """Cancels expired messages on a fixed interval.

    Args:
        shutdown: Shared shutdown signal, normally the outbox worker's.
        interval_seconds: Seconds between passes.
        batch_size: Maximum rows cancelled per pass.
        event_publisher: Lifecycle event publisher. Defaults to a new
            :class:`NotificationEventPublisher`.

    """

    def __init__(
        self,
        *,
        shutdown: asyncio.Event,
        interval_seconds: float,
        batch_size: int,
        event_publisher: NotificationEventPublisher | None = None,
    ) -> None:
        """Build a sweep bound to an existing shutdown event."""
        self._shutdown = shutdown
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._event_publisher = event_publisher or NotificationEventPublisher()

    async def run_loop(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Sweep until shutdown is signalled.

        Args:
            session_factory: Factory producing a session per pass.

        """
        logger.info(
            "Message expiry sweep started",
            interval_seconds=self._interval,
            batch_size=self._batch_size,
        )
        while not self._shutdown.is_set():
            try:
                async with session_factory() as db:
                    expired = await self.sweep_once(db)
                if expired:
                    logger.info("Cancelled expired messages", count=expired)
            except Exception:
                # A DB outage must not kill the task; the next pass retries.
                logger.exception("Message expiry sweep pass failed")

            if await self._wait_or_shutdown(self._interval):
                break
        logger.info("Message expiry sweep exited cleanly")

    async def sweep_once(self, db: AsyncSession) -> int:
        """Cancel one batch of expired messages.

        Args:
            db: Session the batch runs in. Committed on success.

        Returns:
            Number of rows moved to ``CANCELLED``.

        """
        result = await db.execute(self.build_expired_query(self._batch_size))
        claimed = list(result.scalars().all())
        if not claimed:
            return 0

        for message in claimed:
            await expire_message(db, message, self._event_publisher)
        await db.commit()
        return len(claimed)

    @staticmethod
    def build_expired_query(limit: int) -> Select[tuple[Message]]:
        """Build the claim query for rows past their expiry.

        Mirrors the worker's pending claim locking (``FOR UPDATE SKIP LOCKED``)
        over every state still awaiting delivery, narrowed to rows carrying an
        elapsed ``expires_at``. Matches the partial index
        ``ix_messages_expires_at``.

        Args:
            limit: Maximum rows to claim.

        Returns:
            A ``Select`` with ``FOR UPDATE SKIP LOCKED`` applied.

        """
        return (
            select(Message)
            .where(
                Message.status.in_(EXPIRABLE_STATUSES),
                Message.expires_at.is_not(None),
                Message.expires_at <= func.now(),
            )
            .order_by(Message.expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

    async def _wait_or_shutdown(self, seconds: float) -> bool:
        """Wait for shutdown or for ``seconds``, whichever comes first.

        Args:
            seconds: Maximum seconds to wait.

        Returns:
            ``True`` if shutdown was signalled, ``False`` on timeout.

        """
        try:
            await asyncio.wait_for(self._shutdown.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True

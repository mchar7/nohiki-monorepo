"""Generic saga state management with optimistic locking and outbox integration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki_observability import get_logger
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from nohiki_db_utils.outbox import OutboxEventParams, OutboxPayload, OutboxWriter
from nohiki_db_utils.saga.models import SagaBaseMixin, SagaStatus
from nohiki_db_utils.state_machine import InvalidTransitionError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

DEFAULT_STALE_BATCH_SIZE = 1_000


class SagaRepository[T: SagaBaseMixin]:
    """Generic saga state management with optimistic locking and outbox integration.

    Provides CRUD operations for saga rows, callback recording with
    automatic completion detection, and atomic completion with outbox
    event writing.

    The repository uses optimistic locking (version column) to safely
    handle concurrent callbacks arriving on different Kafka consumer
    threads or pods.

    """

    def __init__(self, model_cls: type[T]) -> None:
        """Initialize with the concrete saga model class.

        Args:
            model_cls: SQLAlchemy model class extending SagaBaseMixin.

        """
        self._model_cls = model_cls

    async def create(self, db: AsyncSession, saga: T) -> T:
        """Insert a new saga row.

        Args:
            db: Async SQLAlchemy session (caller manages transaction).
            saga: Saga instance to persist.

        Returns:
            The persisted saga instance (with server-generated defaults populated).

        """
        db.add(saga)
        await db.flush()
        await db.refresh(saga)
        logger.debug(
            "Created saga",
            saga_id=str(saga.id),
            model=self._model_cls.__name__,
            expected_callbacks=saga.expected_callbacks,
        )
        return saga

    async def load(self, db: AsyncSession, saga_id: UUID) -> T | None:
        """Load a saga by ID.

        Args:
            db: Async SQLAlchemy session.
            saga_id: UUID of the saga to load.

        Returns:
            The saga instance, or None if not found.

        """
        result = await db.execute(
            select(self._model_cls).where(self._model_cls.id == saga_id),
        )
        return result.scalar_one_or_none()

    async def record_callback(
        self,
        db: AsyncSession,
        saga_id: UUID,
        *,
        update_fn: Callable[[T], None],
    ) -> tuple[T, bool]:
        """Record a callback arrival with optimistic locking.

        Increments ``received_callbacks``, applies ``update_fn`` to store
        callback-specific data, and bumps the version. Uses a WHERE clause
        on the current version to detect concurrent modifications.

        Args:
            db: Async SQLAlchemy session (caller manages transaction).
            saga_id: UUID of the saga to update.
            update_fn: Function that mutates the saga with callback data
                (e.g., sets ``retrieval_embedding_json``).

        Returns:
            Tuple of (updated saga, is_complete). ``is_complete`` is True
            when ``received_callbacks >= expected_callbacks``.

        Raises:
            NoResultFound: If saga not found or version conflict (optimistic lock).
            InvalidTransitionError: If saga is not in PENDING state.

        """
        saga = await self._load_for_update(db, saga_id)

        if saga.status != SagaStatus.PENDING:
            raise InvalidTransitionError(
                entity_type=self._model_cls.__name__,
                current_state=saga.status.value,
                target_state="callback recording",
                allowed_targets=frozenset({"PENDING"}),
            )

        update_fn(saga)
        saga.received_callbacks += 1
        saga.version += 1

        await db.flush()
        await db.refresh(saga)

        logger.debug(
            "Recorded callback",
            saga_id=str(saga_id),
            received=saga.received_callbacks,
            expected=saga.expected_callbacks,
            is_complete=saga.is_complete,
        )

        return saga, saga.is_complete

    async def complete(
        self,
        db: AsyncSession,
        saga: T,
        *,
        outbox_writer: OutboxWriter,
        outbox_params: OutboxEventParams,
        outbox_event: OutboxPayload,
    ) -> None:
        """Transition saga to COMPLETED and write outbox event atomically.

        Args:
            db: Async SQLAlchemy session (caller manages transaction).
            saga: The saga to complete (must be PENDING with all callbacks received).
            outbox_writer: Writer for the transactional outbox.
            outbox_params: Outbox event parameters (aggregate_type, aggregate_id, event_type).
            outbox_event: Protobuf message to write to outbox.

        Raises:
            InvalidTransitionError: If saga is not PENDING or callbacks are incomplete.

        """
        if not saga.is_complete:
            raise InvalidTransitionError(
                entity_type=self._model_cls.__name__,
                current_state=f"{saga.status.value} ({saga.received_callbacks}/{saga.expected_callbacks} callbacks)",
                target_state=SagaStatus.COMPLETED.value,
                allowed_targets=frozenset(),
            )
        saga.transition_to(SagaStatus.COMPLETED)
        await outbox_writer.write_event(db=db, params=outbox_params, event=outbox_event)
        await db.flush()

        logger.info(
            "Completed saga",
            saga_id=str(saga.id),
            model=self._model_cls.__name__,
        )

    async def fail(
        self,
        db: AsyncSession,
        saga_id: UUID,
        *,
        reason: str,
    ) -> None:
        """Transition saga to FAILED.

        Args:
            db: Async SQLAlchemy session (caller manages transaction).
            saga_id: UUID of the saga to fail.
            reason: Human-readable failure reason for logging.

        Raises:
            NoResultFound: If saga not found.
            InvalidTransitionError: If saga is not in PENDING state.

        """
        saga = await self._load_for_update(db, saga_id)
        saga.transition_to(SagaStatus.FAILED)
        await db.flush()

        logger.warning(
            "Failed saga",
            saga_id=str(saga_id),
            model=self._model_cls.__name__,
            reason=reason,
        )

    async def find_stale(
        self,
        db: AsyncSession,
        *,
        cutoff: datetime,
        limit: int = DEFAULT_STALE_BATCH_SIZE,
    ) -> Sequence[T]:
        """Find PENDING sagas that have expired.

        Args:
            db: Async SQLAlchemy session.
            cutoff: Sagas with ``expires_at`` before this are stale.
            limit: Maximum rows to lock and return in one sweep.

        Returns:
            Sequence of stale saga instances.

        """
        result = await db.execute(
            select(self._model_cls)
            .where(
                self._model_cls.status == SagaStatus.PENDING,
                self._model_cls.expires_at < cutoff,
            )
            .order_by(self._model_cls.expires_at, self._model_cls.id)
            .limit(limit)
            .with_for_update(skip_locked=True),
        )
        return result.scalars().all()

    async def expire_stale(
        self,
        db: AsyncSession,
        *,
        max_age: timedelta,
    ) -> int:
        """Transition one deterministic batch of expired PENDING sagas to EXPIRED.

        Args:
            db: Async SQLAlchemy session (caller manages transaction).
            max_age: Sagas older than this are expired.

        Returns:
            Number of sagas expired.

        """
        cutoff = datetime.now(UTC) - max_age
        stale = await self.find_stale(db, cutoff=cutoff, limit=DEFAULT_STALE_BATCH_SIZE)

        for saga in stale:
            saga.transition_to(SagaStatus.EXPIRED)

        count = len(stale)
        if count > 0:
            await db.flush()
            logger.info(
                "Expired stale sagas",
                model=self._model_cls.__name__,
                count=count,
            )

        return count

    async def _load_for_update(self, db: AsyncSession, saga_id: UUID) -> T:
        """Load saga with FOR UPDATE lock.

        Args:
            db: Async SQLAlchemy session.
            saga_id: UUID of the saga to load.

        Returns:
            The saga instance.

        Raises:
            NoResultFound: If saga not found.

        """
        result = await db.execute(
            select(self._model_cls).where(self._model_cls.id == saga_id).with_for_update(),
        )
        saga = result.scalar_one_or_none()
        if saga is None:
            msg = f"Saga {saga_id} not found"
            raise NoResultFound(msg)
        return saga

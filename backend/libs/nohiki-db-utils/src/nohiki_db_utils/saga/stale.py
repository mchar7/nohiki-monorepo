"""Periodic detector for stale/stuck saga rows."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from nohiki_db_utils.saga.models import SagaBaseMixin
from nohiki_db_utils.saga.repository import SagaRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class StaleSagaDetector[T: SagaBaseMixin]:
    """Periodic detector for stale/stuck saga rows.

    Intended to be called on a schedule (e.g., every 5 minutes via an asyncio BG task in the service lifespan).
    Finds all PENDING sagas past their ``expires_at`` and transitions them to EXPIRED.

    Usage:
        detector = StaleSagaDetector(MyEmbeddingSaga, max_age=timedelta(minutes=30))

        # In periodic task:
        expired_count = await detector.run(db)

    """

    def __init__(
        self,
        model_cls: type[T],
        max_age: timedelta = timedelta(minutes=30),
    ) -> None:
        """Initialize the stale saga detector.

        Args:
            model_cls: SQLAlchemy model class extending SagaBaseMixin.
            max_age: Sagas older than this are considered stale.

        """
        self._repo = SagaRepository[T](model_cls)
        self._max_age = max_age
        self._model_name = model_cls.__name__

    async def run(self, db: AsyncSession) -> int:
        """Detect and expire stale sagas.

        Args:
            db: Async SQLAlchemy session (caller manages transaction).

        Returns:
            Number of sagas expired.

        """
        count = await self._repo.expire_stale(db, max_age=self._max_age)
        if count > 0:
            logger.warning(
                "Detected stale sagas",
                model=self._model_name,
                expired_count=count,
                max_age_seconds=self._max_age.total_seconds(),
            )
        return count

"""Correlation repository for database operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from nohiki.common.v1 import UserFeedback
from nohiki_observability import get_logger
from sqlalchemy import case, func, select, update
from sqlalchemy.engine import CursorResult

from job_correlation_evaluation_service.db.models import Correlation

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CorrelationUpdate:
    """Mutable feedback fields for one correlation."""

    is_viewed: bool | None = None
    is_applied: bool | None = None
    is_dismissed: bool | None = None
    user_feedback: UserFeedback | None = None


class CorrelationNotFoundError(Exception):
    """Raised when a correlation is not found."""

    def __init__(self, correlation_id: UUID) -> None:
        """Initialize with correlation ID."""
        self.correlation_id = correlation_id
        super().__init__(f"Correlation not found: {correlation_id}")


class CorrelationRepository:
    """Repository for correlation CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def get_by_id(self, correlation_id: UUID, user_id: UUID | None = None) -> Correlation | None:
        """Get a correlation by ID, optionally scoped to its owning user."""
        query = select(Correlation).where(Correlation.id == correlation_id)
        if user_id is not None:
            query = query.where(Correlation.user_id == user_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def update(
        self,
        correlation_id: UUID,
        changes: CorrelationUpdate,
        *,
        user_id: UUID | None = None,
    ) -> Correlation:
        """Update feedback fields; the surrounding unit of work owns commit."""
        correlation = await self.get_by_id(correlation_id, user_id)
        if correlation is None:
            raise CorrelationNotFoundError(correlation_id)

        if changes.is_viewed is not None:
            correlation.is_viewed = changes.is_viewed
        if changes.is_applied is not None:
            correlation.is_applied = changes.is_applied
        if changes.is_dismissed is not None:
            correlation.is_dismissed = changes.is_dismissed
        if changes.user_feedback is not None:
            correlation.user_feedback = changes.user_feedback

        await self._session.flush()
        await self._session.refresh(correlation)
        return correlation

    async def get_feedback_stats(self) -> dict[str, int | dict[str, int]]:
        """Get aggregated feedback statistics.

        Uses a single query with conditional aggregation for O(1) database
        round-trip instead of O(k) sequential queries.
        """
        has_feedback = (
            (Correlation.is_viewed.is_(True))
            | (Correlation.is_applied.is_(True))
            | (Correlation.is_dismissed.is_(True))
            | (Correlation.user_feedback.isnot(None))
        )

        query = select(
            func.count(case((has_feedback, 1))).label("total_feedback"),
            func.count(case((Correlation.is_viewed.is_(True), 1))).label("viewed"),
            func.count(case((Correlation.is_applied.is_(True), 1))).label("applied"),
            func.count(case((Correlation.is_dismissed.is_(True), 1))).label("dismissed"),
            func.count(case((Correlation.user_feedback == UserFeedback.POSITIVE, 1))).label("positive"),
            func.count(case((Correlation.user_feedback == UserFeedback.NEGATIVE, 1))).label("negative"),
            func.count(case((Correlation.feature_vector.isnot(None) & has_feedback, 1))).label("training_samples"),
        )

        result = await self._session.execute(query)
        row = result.one()

        return {
            "total_feedback_count": row.total_feedback or 0,
            "feedback_by_type": {
                "viewed": row.viewed or 0,
                "applied": row.applied or 0,
                "dismissed": row.dismissed or 0,
                "positive": row.positive or 0,
                "negative": row.negative or 0,
            },
            "training_samples_available": row.training_samples or 0,
        }

    async def get_for_training(
        self,
        min_date: datetime | None = None,
        max_date: datetime | None = None,
        limit: int = 10000,
    ) -> list[Correlation]:
        """Get correlations with feedback signals for training export."""
        query = select(Correlation).where(
            Correlation.feature_vector.isnot(None),
            Correlation.is_viewed.is_(True)
            | Correlation.is_applied.is_(True)
            | Correlation.is_dismissed.is_(True)
            | Correlation.user_feedback.isnot(None),
        )

        if min_date is not None:
            query = query.where(Correlation.created_at >= min_date)
        if max_date is not None:
            query = query.where(Correlation.created_at <= max_date)

        query = query.order_by(Correlation.created_at.desc()).limit(limit)

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def bulk_update_viewed(self, correlation_ids: list[UUID]) -> int:
        """Mark correlations viewed; the surrounding unit of work owns commit."""
        if not correlation_ids:
            return 0

        stmt = update(Correlation).where(Correlation.id.in_(correlation_ids)).values(is_viewed=True)
        result = cast(CursorResult[tuple[()]], await self._session.execute(stmt))
        return result.rowcount if result.rowcount is not None else 0

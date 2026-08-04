"""Feedback repository for database operations on feedback tables."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.feedback.v1 import ScoreFeedbackType
from nohiki_observability import get_logger
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from job_correlation_evaluation_service.db.feedback_models import (
    AsymmetricFeedbackModel,
    ManualAdjustmentModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ListingFeedbackAggregate:
    """Aggregate feedback statistics for a listing across all users."""

    listing_id: UUID
    good_count: int
    too_high_count: int
    too_low_count: int

    @property
    def total_count(self) -> int:
        """Total feedback count for this listing."""
        return self.good_count + self.too_high_count + self.too_low_count

    @property
    def quality_signal(self) -> float:
        """Compute a quality signal from feedback.

        Returns a value between -1.0 (all TOO_HIGH) and 1.0 (all TOO_LOW).
        0.0 indicates balanced feedback or all GOOD.

        TOO_HIGH feedback suggests listing is oversold (low quality).
        TOO_LOW feedback suggests listing is undervalued (high quality).
        """
        if self.total_count == 0:
            return 0.0
        return (self.too_low_count - self.too_high_count) / self.total_count


@dataclass(frozen=True, slots=True)
class ManualAdjustmentCreate:
    """Validated fields for a manual score adjustment."""

    original_score: float
    adjusted_score: float
    reasoning: str
    request_id: str | None = None


class FeedbackRepository:
    """Repository for feedback CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session."""
        self._session = session

    async def create_asymmetric_feedback(
        self,
        correlation_id: UUID,
        user_id: UUID,
        feedback_type: ScoreFeedbackType,
        request_id: str | None = None,
    ) -> AsymmetricFeedbackModel:
        """Create asymmetric feedback for a correlation.

        Args:
            correlation_id: The correlation being rated.
            user_id: The user providing feedback.
            feedback_type: GOOD, TOO_HIGH, or TOO_LOW.
            request_id: Idempotency key for the originating request.

        Returns:
            The created feedback model.

        """
        if request_id is not None:
            stmt = (
                insert(AsymmetricFeedbackModel)
                .values(
                    correlation_id=correlation_id,
                    user_id=user_id,
                    request_id=request_id,
                    feedback_type=feedback_type.name,
                )
                .on_conflict_do_nothing(index_elements=["request_id"])
            )
            await self._session.execute(stmt)
            result = await self._session.execute(
                select(AsymmetricFeedbackModel).where(AsymmetricFeedbackModel.request_id == request_id)
            )
            return result.scalar_one()

        model = AsymmetricFeedbackModel(
            correlation_id=correlation_id,
            user_id=user_id,
            feedback_type=feedback_type.name,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)

        logger.info(
            "Created asymmetric feedback",
            feedback_id=str(model.id),
            correlation_id=str(correlation_id),
            user_id=str(user_id),
            feedback_type=feedback_type.name,
        )

        return model

    async def create_manual_adjustment(
        self,
        correlation_id: UUID,
        user_id: UUID,
        adjustment: ManualAdjustmentCreate,
    ) -> ManualAdjustmentModel:
        """Create an idempotent, finite manual score adjustment."""
        original_score = adjustment.original_score
        adjusted_score = adjustment.adjusted_score
        reasoning = adjustment.reasoning
        request_id = adjustment.request_id
        if not math.isfinite(original_score) or not 0.0 <= original_score <= 1.0:
            msg = "original_score must be finite and between 0 and 1"
            raise ValueError(msg)
        if not math.isfinite(adjusted_score) or not 0.0 <= adjusted_score <= 1.0:
            msg = "adjusted_score must be finite and between 0 and 1"
            raise ValueError(msg)
        if request_id is not None:
            stmt = (
                insert(ManualAdjustmentModel)
                .values(
                    correlation_id=correlation_id,
                    user_id=user_id,
                    request_id=request_id,
                    original_score=original_score,
                    adjusted_score=adjusted_score,
                    reasoning=reasoning,
                )
                .on_conflict_do_nothing(index_elements=["request_id"])
            )
            await self._session.execute(stmt)
            result = await self._session.execute(
                select(ManualAdjustmentModel).where(ManualAdjustmentModel.request_id == request_id)
            )
            return result.scalar_one()

        model = ManualAdjustmentModel(
            correlation_id=correlation_id,
            user_id=user_id,
            original_score=original_score,
            adjusted_score=adjusted_score,
            reasoning=reasoning,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)

        logger.info(
            "Created manual adjustment",
            adjustment_id=str(model.id),
            correlation_id=str(correlation_id),
            user_id=str(user_id),
            original_score=original_score,
            adjusted_score=adjusted_score,
        )

        return model

    async def get_asymmetric_feedback_by_id(
        self,
        feedback_id: UUID,
    ) -> AsymmetricFeedbackModel | None:
        """Get asymmetric feedback by ID."""
        result = await self._session.execute(
            select(AsymmetricFeedbackModel).where(AsymmetricFeedbackModel.id == feedback_id)
        )
        return result.scalar_one_or_none()

    async def get_manual_adjustment_by_id(
        self,
        adjustment_id: UUID,
    ) -> ManualAdjustmentModel | None:
        """Get manual adjustment by ID."""
        result = await self._session.execute(
            select(ManualAdjustmentModel).where(ManualAdjustmentModel.id == adjustment_id)
        )
        return result.scalar_one_or_none()

    async def get_feedback_for_correlation(
        self,
        correlation_id: UUID,
    ) -> list[AsymmetricFeedbackModel]:
        """Get all asymmetric feedback for a correlation."""
        result = await self._session.execute(
            select(AsymmetricFeedbackModel)
            .where(AsymmetricFeedbackModel.correlation_id == correlation_id)
            .order_by(AsymmetricFeedbackModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_adjustments_for_correlation(
        self,
        correlation_id: UUID,
    ) -> list[ManualAdjustmentModel]:
        """Get all manual adjustments for a correlation."""
        result = await self._session.execute(
            select(ManualAdjustmentModel)
            .where(ManualAdjustmentModel.correlation_id == correlation_id)
            .order_by(ManualAdjustmentModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_feedback_for_correlation(
        self,
        correlation_id: UUID,
        user_id: UUID,
    ) -> AsymmetricFeedbackModel | None:
        """Get a user's most recent asymmetric feedback for a correlation."""
        result = await self._session.execute(
            select(AsymmetricFeedbackModel)
            .where(
                AsymmetricFeedbackModel.correlation_id == correlation_id,
                AsymmetricFeedbackModel.user_id == user_id,
            )
            .order_by(AsymmetricFeedbackModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_feedback_by_type(
        self,
        correlation_id: UUID,
    ) -> dict[ScoreFeedbackType, int]:
        """Count feedback by type for a correlation.

        Returns a dictionary mapping each feedback type to its count.
        """
        result = await self._session.execute(
            select(
                AsymmetricFeedbackModel.feedback_type,
                func.count().label("feedback_count"),
            )
            .where(AsymmetricFeedbackModel.correlation_id == correlation_id)
            .group_by(AsymmetricFeedbackModel.feedback_type)
        )

        counts: dict[ScoreFeedbackType, int] = {
            ScoreFeedbackType.GOOD: 0,
            ScoreFeedbackType.TOO_HIGH: 0,
            ScoreFeedbackType.TOO_LOW: 0,
        }

        for feedback_type_name, feedback_count in result:
            feedback_type = ScoreFeedbackType[feedback_type_name]
            counts[feedback_type] = feedback_count

        return counts

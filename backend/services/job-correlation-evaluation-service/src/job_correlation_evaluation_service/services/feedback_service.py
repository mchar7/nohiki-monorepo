"""Feedback service for L2R training data collection."""

from __future__ import annotations

from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from nohiki.common.v1 import UserFeedback
from nohiki.job.correlation.v1 import FeedbackType
from nohiki_observability import get_logger

from job_correlation_evaluation_service.repositories.correlation_repository import (
    CorrelationRepository,
    CorrelationUpdate,
)

if TYPE_CHECKING:
    from job_correlation_evaluation_service.db.models import Correlation

logger = get_logger(__name__)


class CorrelationFeedbackService:
    """Service for managing correlation feedback and L2R training data."""

    LABEL_MAP: ClassVar[dict[str, float]] = {
        "applied": 5.0,
        "liked": 4.0,
        "saved": 3.5,
        "viewed": 2.0,
        "dismissed": 0.5,
        "disliked": 0.0,
        "not_interested": 0.0,
    }

    def __init__(self, repository: CorrelationRepository) -> None:
        """Initialize the feedback service."""
        self._repo = repository

    async def record_feedback(
        self,
        correlation_id: UUID,
        feedback_type: FeedbackType,
        user_id: UUID | None = None,
    ) -> Correlation:
        """Record user feedback on a correlation.

        Updates the appropriate flags based on feedback type:
        - VIEWED: Sets is_viewed = True
        - APPLIED: Sets is_applied = True
        - DISMISSED: Sets is_dismissed = True
        - SAVED/LIKED: Sets user_feedback = POSITIVE
        - DISLIKED: Sets user_feedback = NEGATIVE

        Args:
            correlation_id: UUID of the correlation to update
            feedback_type: Protobuf FeedbackType enum
            user_id: Owning user UUID used to scope event-driven writes.

        Returns:
            Updated Correlation object

        Raises:
            CorrelationNotFoundError: If correlation doesn't exist

        """
        logger.info(
            "Recording feedback",
            correlation_id=str(correlation_id),
            feedback_type=feedback_type.name,
        )
        if feedback_type == FeedbackType.VIEWED:
            changes = CorrelationUpdate(is_viewed=True)
        elif feedback_type == FeedbackType.APPLIED:
            changes = CorrelationUpdate(is_applied=True, is_viewed=True)
        elif feedback_type == FeedbackType.DISMISSED:
            changes = CorrelationUpdate(is_dismissed=True)
        elif feedback_type in (FeedbackType.SAVED, FeedbackType.LIKED):
            changes = CorrelationUpdate(
                user_feedback=UserFeedback.POSITIVE,
                is_viewed=True,
            )
        elif feedback_type == FeedbackType.DISLIKED:
            changes = CorrelationUpdate(user_feedback=UserFeedback.NEGATIVE)
        else:
            msg = f"Unknown feedback type: {feedback_type}"
            raise ValueError(msg)
        update_correlation = partial(
            self._repo.update,
            correlation_id,
            **({"user_id": user_id} if user_id is not None else {}),
        )
        return await update_correlation(**changes.values())

    async def get_stats(self) -> dict[str, int | dict[str, int]]:
        """Get feedback statistics for monitoring and analytics.

        Returns:
            Dictionary containing:
            - total_feedback_count: Total correlations with any feedback
            - feedback_by_type: Breakdown by feedback type
            - training_samples_available: Correlations with feature vectors and feedback

        """
        return await self._repo.get_feedback_stats()

    async def export_training_data(
        self,
        min_date: datetime | None = None,
        max_date: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, str | float | list[float]]]:
        """Export training data for L2R model training.

        Exports correlations with feedback signals in a format suitable for
        LightGBM LambdaMART training. Each sample includes:
        - correlation_id: Unique identifier
        - label: Computed relevance label (0.0 - 5.0)
        - features: Feature vector stored at scoring time
        - query_id: User ID for LambdaMART grouping

        Args:
            min_date: Optional minimum creation date filter
            max_date: Optional maximum creation date filter
            limit: Maximum samples to export (default 10000)

        Returns:
            List of training samples with computed labels

        """
        correlations = await self._repo.get_for_training(
            min_date=min_date,
            max_date=max_date,
            limit=limit,
        )

        samples: list[dict[str, str | float | list[float]]] = []
        for corr in correlations:
            label = self._compute_label(corr)
            if label is not None and corr.feature_vector is not None:
                samples.append(
                    {
                        "correlation_id": str(corr.id),
                        "label": label,
                        "features": corr.feature_vector,
                        "query_id": str(corr.user_id),
                        "feature_schema_version": corr.feature_schema_version,
                    }
                )

        logger.info(
            "Exported training data",
            total_correlations=len(correlations),
            samples_with_labels=len(samples),
            min_date=str(min_date) if min_date else None,
            max_date=str(max_date) if max_date else None,
        )

        return samples

    def _compute_label(self, correlation: Correlation) -> float | None:
        """Compute training label from feedback signals.

        Label hierarchy (higher takes precedence):
        1. Applied (5.0) - strongest positive signal
        2. Liked (4.0) - explicit positive
        3. Saved (3.5) - intent to revisit
        4. Viewed (2.0) - implicit positive
        5. Dismissed (0.5) - explicit negative
        6. Disliked (0.0) - strongest negative

        Returns None if no feedback signal exists.
        """
        if correlation.is_applied:
            return 5.0

        if correlation.user_feedback == UserFeedback.POSITIVE:
            return 4.0

        if correlation.is_viewed and not correlation.is_dismissed:
            return 2.0

        if correlation.is_dismissed:
            return 0.5

        if correlation.user_feedback == UserFeedback.NEGATIVE:
            return 0.0

        return None

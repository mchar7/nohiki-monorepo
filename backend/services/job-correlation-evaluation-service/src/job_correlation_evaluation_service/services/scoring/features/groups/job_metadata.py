"""Job metadata feature extraction."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from job_correlation_evaluation_service.services.scoring.config import FreshnessScoringConfig
from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup
from job_correlation_evaluation_service.services.scoring.listing_quality import (
    ListingQualityPredictor,
)

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class JobMetadataFeatureGroup(FeatureGroup):
    """Extract job metadata features (indices 22-24).

    Features:
        - JOB_AGE_HOURS: Job posting age in hours (for freshness)
        - LISTING_FEEDBACK_COUNT: Total feedback count for the listing
        - LISTING_QUALITY_SCORE: Predicted quality score from feedback

    Design: Raw values for job age and listing quality signals.

    """

    def __init__(self, listing_quality_predictor: ListingQualityPredictor | None = None) -> None:
        """Initialize job metadata feature group.

        Args:
            listing_quality_predictor: Optional predictor for listing quality scores.

        """
        self._listing_quality_predictor = listing_quality_predictor
        self._freshness = FreshnessScoringConfig()

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract job metadata features into feature vector."""
        job = context.job
        feedback_aggregate = context.feedback_aggregate

        # Direct attribute access - posted_at is datetime | None
        posted_at = job.posted_at
        if posted_at is not None:
            features[FeatureIndex.JOB_AGE_HOURS] = float(_compute_job_age_hours(posted_at))
        else:
            features[FeatureIndex.JOB_AGE_HOURS] = math.nan

        if feedback_aggregate is not None:
            features[FeatureIndex.LISTING_FEEDBACK_COUNT] = float(feedback_aggregate.total_feedback)
        else:
            features[FeatureIndex.LISTING_FEEDBACK_COUNT] = 0.0

        if self._listing_quality_predictor is not None and feedback_aggregate is not None:
            features[FeatureIndex.LISTING_QUALITY_SCORE] = self._listing_quality_predictor.predict(feedback_aggregate)
        else:
            features[FeatureIndex.LISTING_QUALITY_SCORE] = math.nan

        age_hours = features[FeatureIndex.JOB_AGE_HOURS]
        if not math.isnan(age_hours):
            max_age_hours = 24.0 * self._freshness.max_age_days
            context.factor_scores["recency"] = max(0.0, 1.0 - float(age_hours) / max_age_hours)


def _compute_job_age_hours(posted_at: datetime) -> float:
    """Compute raw job age in hours for sub-day freshness granularity."""
    now = datetime.now(UTC)

    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)

    delta = now - posted_at
    return max(0.0, delta.total_seconds() / 3600.0)

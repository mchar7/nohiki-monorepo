"""Deterministic listing quality signal from aggregate feedback.

The quality signal is computed from bounded feedback ratios and counts. It does
not depend on serialized artifacts or provider-specific runtime state.

The quality score becomes feature index 14 (LISTING_QUALITY_SCORE) in the L2R model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from job_correlation_evaluation_service.services.scoring.config import (
    ListingQualityScoringConfig,
    get_scoring_service_settings,
)


@lru_cache(maxsize=1)
def _get_listing_quality_config() -> ListingQualityScoringConfig:
    """Get listing quality config from service settings."""
    return get_scoring_service_settings().listing_quality


@dataclass(frozen=True, slots=True)
class ListingFeedbackAggregate:
    """Aggregate feedback statistics for a single listing."""

    listing_id: UUID
    good_count: int
    too_high_count: int
    too_low_count: int

    @property
    def total_feedback(self) -> int:
        """Total count of all feedback signals."""
        return self.good_count + self.too_high_count + self.too_low_count

    @property
    def good_ratio(self) -> float:
        """Ratio of GOOD feedback to total feedback."""
        total = self.total_feedback
        if total == 0:
            return _get_listing_quality_config().neutral_quality
        return self.good_count / total

    @property
    def too_high_ratio(self) -> float:
        """Ratio of TOO_HIGH feedback to total feedback."""
        total = self.total_feedback
        if total == 0:
            return 0.0
        return self.too_high_count / total

    @property
    def too_low_ratio(self) -> float:
        """Ratio of TOO_LOW feedback to total feedback."""
        total = self.total_feedback
        if total == 0:
            return 0.0
        return self.too_low_count / total

    @property
    def quality_signal(self) -> float:
        """Return a bounded quality signal from feedback ratios and count."""
        config = _get_listing_quality_config()
        if self.total_feedback < config.min_feedback_for_signal:
            return config.neutral_quality

        quality = (
            config.neutral_quality
            - config.too_high_penalty * self.too_high_ratio
            + config.too_low_bonus * self.too_low_ratio
        )
        return max(0.0, min(1.0, quality))


class ListingQualityPredictor:
    """Deterministic predictor backed by aggregate feedback statistics."""

    def predict(self, aggregate: ListingFeedbackAggregate) -> float:
        """Return the bounded deterministic quality signal for a listing."""
        return aggregate.quality_signal

    def predict_cold_start(self) -> float:
        """Return the neutral score for listings without feedback."""
        return _get_listing_quality_config().neutral_quality

    @classmethod
    def create_untrained(cls) -> ListingQualityPredictor:
        """Create a deterministic predictor for cold-start scenarios."""
        return cls()

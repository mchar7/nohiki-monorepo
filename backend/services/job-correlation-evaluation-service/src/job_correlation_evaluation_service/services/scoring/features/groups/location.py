"""Location feature extraction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from nohiki.common.v1 import WorkArrangement

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup
from job_correlation_evaluation_service.services.scoring.features.location_scorer import (
    LocationScorer,
)

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class LocationFeatureGroup(FeatureGroup):
    """Extract RAW location features (indices 2-5).

    Features:
        - DISTANCE_KM: Raw distance in kilometers (NaN if unavailable)
        - IS_SAME_CITY: Binary flag for same city match
        - IS_REMOTE_JOB: Binary flag for remote work arrangement
        - USER_OPEN_TO_RELOCATION: Binary flag for relocation openness

    Design: Provides raw distance values for LightGBM to learn optimal thresholds.

    """

    def __init__(self, location_scorer: LocationScorer | None = None) -> None:
        """Initialize location feature group.

        Args:
            location_scorer: Optional LocationScorer instance (creates default if None).

        """
        self._location_scorer = location_scorer or LocationScorer()

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract location features into feature vector."""
        job = context.job
        profile = context.profile

        job_location = job.location
        job_arrangement = job.work_arrangement
        open_to_relocation = profile.open_to_relocation

        features[FeatureIndex.IS_REMOTE_JOB] = 1.0 if job_arrangement == WorkArrangement.REMOTE else 0.0
        features[FeatureIndex.USER_OPEN_TO_RELOCATION] = 1.0 if open_to_relocation else 0.0

        physical = profile.physical_locations
        remote = profile.remote_locations
        if job_location is None or (not physical and not remote):
            features[FeatureIndex.DISTANCE_KM] = math.nan
            features[FeatureIndex.IS_SAME_CITY] = math.nan
            return

        all_locations = [*physical, *remote]
        result = self._location_scorer.score(
            job_location=job_location,
            profile_locations=all_locations,
            job_work_arrangement=job_arrangement,
            user_work_arrangements=profile.work_arrangements or None,
            open_to_relocation=open_to_relocation,
        )

        features[FeatureIndex.DISTANCE_KM] = result.distance_km if result.distance_km is not None else math.nan
        features[FeatureIndex.IS_SAME_CITY] = 1.0 if result.is_same_city else 0.0
        if result.is_scoreable:
            context.factor_scores["location"] = result.score

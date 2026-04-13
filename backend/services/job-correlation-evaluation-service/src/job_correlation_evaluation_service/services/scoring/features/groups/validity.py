"""Validity flags feature extraction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class ValidityFlagsFeatureGroup(FeatureGroup):
    """Set validity flags based on whether data features are present (indices 26-30).

    Features:
        - HAS_LOCATION_DATA: 1.0 if location data is available
        - HAS_EXPERIENCE_DATA: 1.0 if experience data is available
        - HAS_SALARY_DATA: 1.0 if salary data is available
        - HAS_SKILL_DATA: 1.0 if skill requirements exist
        - HAS_LISTING_QUALITY: 1.0 if listing quality score is available

    Note:
        This group MUST be executed LAST as it reads values written by other groups.

    """

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract validity flags into feature vector based on other features."""
        del context
        features[FeatureIndex.HAS_LOCATION_DATA] = 0.0 if math.isnan(features[FeatureIndex.DISTANCE_KM]) else 1.0
        features[FeatureIndex.HAS_EXPERIENCE_DATA] = (
            0.0
            if (
                math.isnan(features[FeatureIndex.JOB_EXPERIENCE_MIN])
                and math.isnan(features[FeatureIndex.JOB_EXPERIENCE_MAX])
            )
            else 1.0
        )
        features[FeatureIndex.HAS_SALARY_DATA] = 0.0 if math.isnan(features[FeatureIndex.JOB_SALARY]) else 1.0
        features[FeatureIndex.HAS_SKILL_DATA] = 1.0 if features[FeatureIndex.SKILL_TOTAL_REQUIRED] > 0 else 0.0
        features[FeatureIndex.HAS_LISTING_QUALITY] = (
            0.0 if math.isnan(features[FeatureIndex.LISTING_QUALITY_SCORE]) else 1.0
        )

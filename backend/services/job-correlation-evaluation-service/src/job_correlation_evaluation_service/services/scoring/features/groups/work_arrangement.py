"""Work arrangement feature extraction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from nohiki.common.v1 import WorkArrangement

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class WorkArrangementFeatureGroup(FeatureGroup):
    """Extract work arrangement match feature (index 25).

    Features:
        - WORK_ARRANGEMENT_MATCH: Binary flag for work arrangement compatibility

    """

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract work arrangement match feature into feature vector."""
        profile = context.profile
        job = context.job

        profile_arrangements = profile.work_arrangements
        job_arrangement = job.work_arrangement

        if job_arrangement == WorkArrangement.UNSPECIFIED or not profile_arrangements:
            features[FeatureIndex.WORK_ARRANGEMENT_MATCH] = math.nan
        else:
            features[FeatureIndex.WORK_ARRANGEMENT_MATCH] = 1.0 if job_arrangement in profile_arrangements else 0.0
            context.factor_scores["work_arrangement"] = features[FeatureIndex.WORK_ARRANGEMENT_MATCH]

"""Skill feature extraction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup
from job_correlation_evaluation_service.services.scoring.features.skill_match_quality import (
    SkillMatchQualityCalculator,
)

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class SkillFeatureGroup(FeatureGroup):
    """Extract GRANULAR skill features (indices 14-19).

    Features:
        - SKILL_MATCH_COUNT: Number of matched skills
        - SKILL_MISSING_COUNT: Number of missing required skills
        - SKILL_TOTAL_REQUIRED: Total job required skills
        - SKILL_AVG_PROFICIENCY: Average proficiency-weighted score
        - SKILL_AVG_PROVENANCE: Average provenance-weighted score
        - SKILL_RELATIONSHIP_COUNT: Count of related skills (graph expansion)

    Design: Multiple granular signals for LightGBM to learn skill matching nuances.

    """

    def __init__(self, skill_quality_calculator: SkillMatchQualityCalculator | None = None) -> None:
        """Initialize skill feature group.

        Args:
            skill_quality_calculator: Optional calculator instance (creates default if None).

        """
        self._skill_quality_calculator = skill_quality_calculator or SkillMatchQualityCalculator()

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract skill features into feature vector."""
        profile = context.profile
        job = context.job

        result = self._skill_quality_calculator.compute(profile.user_skills, job.skill_requirements)

        features[FeatureIndex.SKILL_MATCH_COUNT] = float(result.matched_skill_count)
        features[FeatureIndex.SKILL_MISSING_COUNT] = float(len(result.missing_skill_ids))
        features[FeatureIndex.SKILL_TOTAL_REQUIRED] = float(result.total_job_required_skills)
        features[FeatureIndex.SKILL_AVG_PROFICIENCY] = (
            result.proficiency_weighted_score if not math.isnan(result.proficiency_weighted_score) else math.nan
        )
        features[FeatureIndex.SKILL_AVG_PROVENANCE] = (
            result.provenance_weighted_score if not math.isnan(result.provenance_weighted_score) else math.nan
        )
        features[FeatureIndex.SKILL_RELATIONSHIP_COUNT] = float(
            len(result.expanded_user_skill_ids) - result.total_user_skills
        )
        if result.has_skill_data:
            context.factor_scores["skills"] = result.skill_match_quality

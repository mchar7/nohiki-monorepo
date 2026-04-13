"""Experience feature extraction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from nohiki.common.v1 import SeniorityLevel

from job_correlation_evaluation_service.services.scoring.config import ExperienceScoringConfig
from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


_TWO_LEVEL_DISTANCE = 2


class ExperienceFeatureGroup(FeatureGroup):
    """Extract RAW experience features (indices 6-10).

    Features:
        - USER_EXPERIENCE_YEARS: User's years of experience
        - JOB_EXPERIENCE_MIN: Job's minimum required experience
        - JOB_EXPERIENCE_MAX: Job's maximum required experience
        - USER_SENIORITY_LEVEL: User's preferred seniority level (max of preferences)
        - JOB_SENIORITY_LEVEL: Job's required seniority level

    Design: Provides raw years/levels for LightGBM to learn over/under-qualification effects.

    """

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract experience features into feature vector."""
        profile = context.profile
        job = context.job

        # Direct attribute access - rigid schema
        exp_pref = profile.experience_preference  # ExperiencePreference | None
        user_years = exp_pref.experience_years if exp_pref else None
        user_seniority_prefs = exp_pref.seniority_levels if exp_pref else []

        job_min = job.experience_years_min  # int | None
        job_max = job.experience_years_max  # int | None
        job_seniority = job.seniority_level  # SeniorityLevel enum (has default)

        features[FeatureIndex.USER_EXPERIENCE_YEARS] = float(user_years) if user_years is not None else math.nan
        features[FeatureIndex.JOB_EXPERIENCE_MIN] = float(job_min) if job_min is not None else math.nan
        features[FeatureIndex.JOB_EXPERIENCE_MAX] = float(job_max) if job_max is not None else math.nan

        if user_seniority_prefs:
            features[FeatureIndex.USER_SENIORITY_LEVEL] = float(max(int(s) for s in user_seniority_prefs))
        else:
            features[FeatureIndex.USER_SENIORITY_LEVEL] = math.nan

        if job_seniority != SeniorityLevel.UNSPECIFIED:
            features[FeatureIndex.JOB_SENIORITY_LEVEL] = float(int(job_seniority))
        else:
            features[FeatureIndex.JOB_SENIORITY_LEVEL] = math.nan

        config = ExperienceScoringConfig()
        scores: list[float] = []
        if user_years is not None and job_min is not None:
            if user_years < job_min:
                gap = job_min - user_years
                span = config.underqualified_max_penalty_years
                scores.append(
                    max(config.underqualified_min_score, 1.0 - gap / span * (1.0 - config.underqualified_min_score))
                )
            elif job_max is not None and user_years > job_max:
                gap = user_years - job_max
                span = config.overqualified_max_penalty_years
                scores.append(
                    max(config.overqualified_min_score, 1.0 - gap / span * (1.0 - config.overqualified_min_score))
                )
            else:
                scores.append(1.0)

        valid_levels = [level for level in user_seniority_prefs if level != SeniorityLevel.UNSPECIFIED]
        if job_seniority != SeniorityLevel.UNSPECIFIED and valid_levels:
            distance = min(abs(int(job_seniority) - int(level)) for level in valid_levels)
            scores.append(
                1.0
                if distance == 0
                else config.seniority_one_level_score
                if distance == 1
                else config.seniority_two_level_score
                if distance == _TWO_LEVEL_DISTANCE
                else config.seniority_three_plus_score
            )
        if scores:
            context.factor_scores["experience"] = sum(scores) / len(scores)

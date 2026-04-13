"""Feature composition for L2R model."""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import numpy as np

from job_correlation_evaluation_service.metrics import get_skill_canonicalization_metrics
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT
from job_correlation_evaluation_service.services.scoring.features.base import (
    FeatureComposition,
    FeatureExtractionContext,
    FeatureGroup,
    PipelineScores,
)
from job_correlation_evaluation_service.services.scoring.features.groups import (
    ExperienceFeatureGroup,
    JobMetadataFeatureGroup,
    LocationFeatureGroup,
    PipelineFeatureGroup,
    SalaryFeatureGroup,
    SemanticFeatureGroup,
    SkillFeatureGroup,
    TaxonomyFeatureGroup,
    ValidityFlagsFeatureGroup,
    WorkArrangementFeatureGroup,
)
from job_correlation_evaluation_service.services.scoring.features.role_relevance import role_relevance
from job_correlation_evaluation_service.services.scoring.listing_quality import (
    ListingQualityPredictor,
)

if TYPE_CHECKING:
    from nohiki.job.listing.v1 import ListingSnapshot
    from nohiki.user.pref.v1 import SearchPrefSnapshot

    from job_correlation_evaluation_service.services.scoring.features.location_scorer import (
        LocationScorer,
    )
    from job_correlation_evaluation_service.services.scoring.features.skill_match_quality import (
        SkillMatchQualityCalculator,
    )
    from job_correlation_evaluation_service.services.scoring.listing_quality import (
        ListingFeedbackAggregate,
    )
    from job_correlation_evaluation_service.services.scoring.skill_relationship_cache import (
        SkillRelationshipCache,
    )


class FeatureComposer:
    """Compose feature groups into a complete feature vector.

    This class orchestrates multiple FeatureGroup implementations to extract
    a complete feature vector for the L2R model. Each group is responsible
    for a specific domain of features.

    Design Principles:
        - Open/Closed: Add new features by adding new groups to the composition
        - Single Responsibility: Each group handles one domain
        - Dependency Injection: Groups can be customized or mocked for testing

    Feature Vector Layout (32 dimensions):
        0-1: Pipeline scores (MaxSim, Rerank)
        2-5: Location features (distance_km, is_same_city, is_remote, relocation)
        6-10: Experience features (user_years, job_min, job_max, user_seniority, job_seniority)
        11-13: Salary features (user_min, user_target, job_salary)
        14-19: Skill features (match_count, missing_count, total_required, avg_prof, avg_prov, relationship_count)
        20: Semantic similarity (skills_cosine_sim)
        21-24: Job metadata (age_hours, feedback_count, quality_score, work_arrangement_match)
        25-29: Validity flags
        30-31: Taxonomy features (skill_graph_min_distance, skill_graph_mean_distance)

    Example:
        >>> composer = FeatureComposer.create_default()
        >>> scores = PipelineScores(maxsim_score=0.78, rerank_score=0.92)
        >>> features = composer.extract(job_snapshot, search_pref, scores)
        >>> features.shape
        (32,)

    """

    def __init__(self, feature_groups: list[FeatureGroup]) -> None:
        """Initialize feature composer.

        Args:
            feature_groups: Ordered list of feature groups to execute.
                           ValidityFlagsFeatureGroup should be last.

        """
        self._feature_groups = feature_groups

    @classmethod
    def create_default(
        cls,
        location_scorer: LocationScorer | None = None,
        skill_quality_calculator: SkillMatchQualityCalculator | None = None,
        listing_quality_predictor: ListingQualityPredictor | None = None,
        relationship_cache: SkillRelationshipCache | None = None,
    ) -> FeatureComposer:
        """Create composer with default feature groups.

        Args:
            location_scorer: Optional LocationScorer instance for location features.
            skill_quality_calculator: Optional calculator for skill features.
            listing_quality_predictor: Optional predictor for listing quality scores.
            relationship_cache: Optional SkillRelationshipCache for taxonomy features.

        Returns:
            Configured FeatureComposer with all standard feature groups.

        """
        return cls(
            [
                PipelineFeatureGroup(),
                LocationFeatureGroup(location_scorer=location_scorer),
                ExperienceFeatureGroup(),
                SalaryFeatureGroup(),
                SkillFeatureGroup(skill_quality_calculator=skill_quality_calculator),
                SemanticFeatureGroup(),
                JobMetadataFeatureGroup(listing_quality_predictor=listing_quality_predictor),
                WorkArrangementFeatureGroup(),
                TaxonomyFeatureGroup(relationship_cache=relationship_cache),
                ValidityFlagsFeatureGroup(),
            ]
        )

    def extract(
        self,
        job: ListingSnapshot,
        profile: SearchPrefSnapshot,
        pipeline_scores: PipelineScores,
        feedback_aggregate: ListingFeedbackAggregate | None = None,
    ) -> FeatureComposition:
        """Extract complete feature vector.

        Args:
            job: Job listing snapshot (ECST from event)
            profile: User search preferences (from ledger or event)
            pipeline_scores: Scores from pipeline (MaxSim, Rerank)
            feedback_aggregate: Optional aggregate feedback for the listing

        Returns:
            Raw 32-value training vector and available deterministic factors.
        """
        start_time = time.perf_counter()
        metrics = get_skill_canonicalization_metrics()

        context = FeatureExtractionContext(
            job=job,
            profile=profile,
            pipeline_scores=pipeline_scores,
            feedback_aggregate=feedback_aggregate,
        )

        try:
            features = np.full(FEATURE_COUNT, math.nan, dtype=np.float32)

            for group in self._feature_groups:
                group.extract(features, context)

        except Exception:
            duration_seconds = time.perf_counter() - start_time
            metrics.record_feature_extraction(duration_seconds, success=False)
            raise
        else:
            duration_seconds = time.perf_counter() - start_time
            metrics.record_feature_extraction(duration_seconds, success=True)
            return FeatureComposition(
                raw_features=features,
                factor_scores=context.factor_scores,
                role_relevance=role_relevance(job, profile),
            )

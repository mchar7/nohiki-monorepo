"""Base classes for feature extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from nohiki.job.listing.v1 import ListingSnapshot
    from nohiki.user.pref.v1 import SearchPrefSnapshot
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.listing_quality import (
        ListingFeedbackAggregate,
    )


type FactorName = Literal["skills", "location", "work_arrangement", "experience", "salary", "recency"]


@dataclass(frozen=True, slots=True)
class FeatureComposition:
    """Raw training features plus available deterministic fit factors."""

    raw_features: NDArray[np.float32]
    factor_scores: dict[FactorName, float]
    role_relevance: float | None = None


@dataclass(frozen=True, slots=True)
class PipelineScores:
    """Scores from the scoring pipeline stages.

    Attributes:
        maxsim_score: Stage 2 ColBERT MaxSim precision score (normalized 0-1)
        rerank_score: Stage 3 LLM reranker score (0.0 if skipped)

    """

    maxsim_score: float
    rerank_score: float


@dataclass(frozen=True, slots=True)
class FeatureExtractionContext:
    """Context data for feature extraction.

    Immutable container passed to all feature groups containing
    the inputs needed for feature extraction.

    Attributes:
        job: Job listing snapshot (ECST from event)
        profile: User search preferences
        pipeline_scores: Scores from prior pipeline stages
        feedback_aggregate: Optional aggregate feedback for the listing

    """

    job: ListingSnapshot
    profile: SearchPrefSnapshot
    pipeline_scores: PipelineScores
    feedback_aggregate: ListingFeedbackAggregate | None = None
    factor_scores: dict[FactorName, float] = field(default_factory=dict)


class FeatureGroup(ABC):
    """Abstract base class for feature extraction groups.

    Each feature group is responsible for extracting a specific domain
    of features into the feature vector at predefined indices.

    Design Principles:
        - Single Responsibility: Each group handles one feature domain
        - Open/Closed: Add new features by creating new groups
        - Testable: Each group can be unit tested independently

    Example:
        >>> class MyFeatureGroup(FeatureGroup):
        ...     def extract(self, features, context):
        ...         features[MY_INDEX] = compute_my_feature(context)

    """

    @abstractmethod
    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract features into the feature array at appropriate indices.

        Args:
            features: Mutable feature array to write values into
            context: Immutable context containing extraction inputs

        Note:
            Implementations should write NaN for missing/invalid data.
            LightGBM handles NaN natively with use_missing=true (default).

        """
        ...

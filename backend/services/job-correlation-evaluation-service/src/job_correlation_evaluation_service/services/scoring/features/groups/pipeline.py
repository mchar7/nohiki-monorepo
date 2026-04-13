"""Pipeline score feature extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class PipelineFeatureGroup(FeatureGroup):
    """Extract pipeline score features (indices 0-1).

    Features:
        - MAXSIM_SCORE: ColBERT MaxSim precision score from Stage 2
        - RERANK_SCORE: LLM reranker score from Stage 3 (0.0 if skipped)
    """

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract pipeline scores into feature vector."""
        features[FeatureIndex.MAXSIM_SCORE] = context.pipeline_scores.maxsim_score
        features[FeatureIndex.RERANK_SCORE] = context.pipeline_scores.rerank_score

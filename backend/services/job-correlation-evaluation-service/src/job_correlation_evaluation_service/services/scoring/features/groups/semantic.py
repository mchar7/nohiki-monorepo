"""Semantic similarity feature extraction."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from nohiki.ml.v1 import EmbeddingVector

from job_correlation_evaluation_service.services.scoring.constants import FeatureIndex
from job_correlation_evaluation_service.services.scoring.features.base import FeatureGroup

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from job_correlation_evaluation_service.services.scoring.features.base import (
        FeatureExtractionContext,
    )


class SemanticFeatureGroup(FeatureGroup):
    """Extract semantic similarity features.

    Features:
        - SKILLS_COSINE_SIM: Cosine similarity between job and user skill embeddings.
          Measures direct skill-to-skill semantic overlap.

    Design: Raw cosine similarity [-1, 1] from pre-computed DENSE embeddings.
    Both embeddings must be in the same space (JobBERT-v2, 1024-dim).

    Note: title_embedding is still computed and stored on listings for future
    occupation-based similarity features (job title vs ISCO occupation embeddings),
    but is not used as an L2R feature here.

    """

    def extract(
        self,
        features: NDArray[np.float32],
        context: FeatureExtractionContext,
    ) -> None:
        """Extract semantic similarity features into feature vector."""
        job = context.job
        profile = context.profile
        user_skills_emb = _get_embedding_values(profile.user_skills_embedding)

        job_skills_emb = _get_embedding_values(job.skills_embedding)

        if job_skills_emb is not None and user_skills_emb is not None:
            features[FeatureIndex.SKILLS_COSINE_SIM] = _cosine_similarity(job_skills_emb, user_skills_emb)
        else:
            features[FeatureIndex.SKILLS_COSINE_SIM] = math.nan


def _get_embedding_values(embedding: EmbeddingVector | None) -> list[float] | None:
    """Extract dense embedding values from EmbeddingVector proto."""
    if embedding is None or embedding.dense is None:
        return None
    values = embedding.dense.values
    if not values:
        return None
    return values


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute raw cosine similarity between two vectors.

    Returns NaN if vectors have incompatible dimensions (e.g. MUVERA 8192-dim
    vs dense 1024-dim), since comparing different embedding spaces is meaningless.
    """
    if len(vec_a) != len(vec_b):
        return math.nan

    a: NDArray[np.float64] = np.asarray(vec_a, dtype=np.float64)
    b: NDArray[np.float64] = np.asarray(vec_b, dtype=np.float64)

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    epsilon = 1e-10
    if norm_a < epsilon or norm_b < epsilon:
        return 0.0

    return float(np.dot(a, b) / (norm_a * norm_b))

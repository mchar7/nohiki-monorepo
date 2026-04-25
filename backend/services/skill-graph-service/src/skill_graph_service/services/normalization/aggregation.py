"""Aggregated embedding computation for matched skills.

Computes mean-pooled, L2-normalized embeddings from existing skill vectors.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final
from uuid import UUID

import numpy as np
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki_common_exceptions import DataIntegrityError

from skill_graph_service.services.embedding_service import EmbeddingVariant, skill_variant_point_id

NORM_EPSILON: Final[float] = 1e-9

RetrieveVectorsFn = Callable[[list[str]], Awaitable[dict[str, list[float]]]]


def build_dense_embedding_vector(
    values: list[float],
    collection_version: str,
) -> EmbeddingVector:
    """Build an EmbeddingVector with DENSE type from raw float values."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=values),
        collection_version=collection_version,
    )


async def compute_aggregated_embedding(
    canonical_ids: list[str],
    collection_version: str,
    *,
    retrieve_vectors: RetrieveVectorsFn,
) -> EmbeddingVector | None:
    """Compute mean-pooled, L2-normalized embedding from existing skill vectors.

    Retrieves the LABEL-variant vector for each canonical skill via deterministic
    UUID5 point IDs (matching the upsert format produced by
    ``skill_variant_point_id``) and aggregates them.

    Args:
        canonical_ids: Canonical skill UUIDs (str) whose LABEL embeddings to aggregate.
        collection_version: Collection version for the result representation.
        retrieve_vectors: Async callable to retrieve vectors by point IDs.

    Returns:
        Mean-pooled, L2-normalized EmbeddingVector, or None when no
        canonical IDs are provided (no meaningful embedding can be computed).

    Raises:
        DataIntegrityError: If any skill embeddings are missing.

    """
    if not canonical_ids:
        return None

    try:
        point_ids = [skill_variant_point_id(UUID(skill_id), EmbeddingVariant.LABEL) for skill_id in canonical_ids]
    except ValueError as exc:
        raise DataIntegrityError(
            resource_type="SkillEmbedding",
            resource_ids=tuple(canonical_ids),
            message=f"Malformed canonical skill UUID in aggregation input: {exc}",
        ) from exc
    vectors = await retrieve_vectors(point_ids)

    if len(vectors) != len(canonical_ids):
        missing = set(point_ids) - set(vectors.keys())
        raise DataIntegrityError(
            resource_type="SkillEmbedding",
            resource_ids=tuple(missing),
        )

    embeddings_np = np.array(list(vectors.values()), dtype=np.float32)
    mean_embedding = np.mean(embeddings_np, axis=0)
    norm = np.linalg.norm(mean_embedding)

    if norm > NORM_EPSILON:
        mean_embedding = mean_embedding / norm

    return build_dense_embedding_vector(mean_embedding.tolist(), collection_version)

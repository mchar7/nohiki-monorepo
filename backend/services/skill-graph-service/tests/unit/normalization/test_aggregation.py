"""Unit tests for normalization aggregation module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest
from nohiki.ml.v1 import EmbeddingType
from nohiki_common_exceptions import DataIntegrityError
from skill_graph_service.services.embedding_service import EmbeddingVariant, skill_variant_point_id
from skill_graph_service.services.normalization.aggregation import (
    build_dense_embedding_vector,
    compute_aggregated_embedding,
)


def _label_point_id(skill_id: str) -> str:
    """Helper: derive the canonical LABEL-variant Qdrant point ID for a skill."""
    return skill_variant_point_id(uuid.UUID(skill_id), EmbeddingVariant.LABEL)


class TestBuildDenseEmbeddingVector:
    """Tests for build_dense_embedding_vector."""

    def test_builds_vector_with_dense_type(self) -> None:
        values = [0.1, 0.2, 0.3]
        result = build_dense_embedding_vector(values, "v1")

        assert result.embedding_type == EmbeddingType.DENSE
        assert result.dense is not None
        assert result.dense.values == values
        assert result.collection_version == "v1"

    def test_handles_empty_values(self) -> None:
        result = build_dense_embedding_vector([], "v2")

        assert result.embedding_type == EmbeddingType.DENSE
        assert result.dense is not None
        assert result.dense.values == []


class TestComputeAggregatedEmbedding:
    """Tests for compute_aggregated_embedding."""

    @pytest.mark.asyncio
    async def test_empty_canonical_ids_returns_none(self) -> None:
        retrieve_vectors = AsyncMock(return_value={})

        result = await compute_aggregated_embedding(
            canonical_ids=[],
            collection_version="v1",
            retrieve_vectors=retrieve_vectors,
        )

        assert result is None
        retrieve_vectors.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_skill_returns_normalized_vector(self) -> None:
        skill_id = str(uuid.uuid4())
        raw_vector = [3.0, 4.0]
        retrieve_vectors = AsyncMock(return_value={_label_point_id(skill_id): raw_vector})

        result = await compute_aggregated_embedding(
            canonical_ids=[skill_id],
            collection_version="v1",
            retrieve_vectors=retrieve_vectors,
        )

        assert result is not None
        assert result.dense is not None
        values = result.dense.values
        norm = np.linalg.norm(values)
        assert norm == pytest.approx(1.0, rel=1e-6)
        # Confirm the call used UUID-shaped point IDs (Qdrant gRPC requirement),
        # not the legacy "{uuid}_label" raw-string format that crashed in production.
        called_with = retrieve_vectors.call_args.args[0]
        assert called_with == [_label_point_id(skill_id)]
        assert "_label" not in called_with[0]

    @pytest.mark.asyncio
    async def test_multiple_skills_computes_mean_pooled(self) -> None:
        skill1 = str(uuid.uuid4())
        skill2 = str(uuid.uuid4())
        retrieve_vectors = AsyncMock(
            return_value={
                _label_point_id(skill1): [1.0, 0.0],
                _label_point_id(skill2): [0.0, 1.0],
            }
        )

        result = await compute_aggregated_embedding(
            canonical_ids=[skill1, skill2],
            collection_version="v1",
            retrieve_vectors=retrieve_vectors,
        )

        assert result is not None
        assert result.dense is not None
        values = result.dense.values
        expected_direction = np.array([0.5, 0.5])
        expected_normalized = expected_direction / np.linalg.norm(expected_direction)
        assert np.allclose(values, expected_normalized, rtol=1e-6)

    @pytest.mark.asyncio
    async def test_raises_data_integrity_error_on_missing_embeddings(self) -> None:
        skill_id = str(uuid.uuid4())
        retrieve_vectors = AsyncMock(return_value={})

        with pytest.raises(DataIntegrityError) as exc_info:
            await compute_aggregated_embedding(
                canonical_ids=[skill_id],
                collection_version="v1",
                retrieve_vectors=retrieve_vectors,
            )

        assert exc_info.value.resource_type == "SkillEmbedding"

    @pytest.mark.asyncio
    async def test_handles_near_zero_norm(self) -> None:
        skill_id = str(uuid.uuid4())
        retrieve_vectors = AsyncMock(return_value={_label_point_id(skill_id): [1e-12, 1e-12]})

        result = await compute_aggregated_embedding(
            canonical_ids=[skill_id],
            collection_version="v1",
            retrieve_vectors=retrieve_vectors,
        )

        assert result is not None
        assert result.dense is not None
        values = result.dense.values
        assert all(abs(v) < 1e-6 for v in values)

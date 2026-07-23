"""Tests for async Qdrant vector client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, MultiVectorData, SparseData
from nohiki_ml_manifest import QdrantCollectionSchema, QdrantSparseConfig, QdrantVectorDefinition
from nohiki_qdrant_client import (
    GroupedSearchParams,
    HybridSearchResult,
    QdrantSettings,
    QdrantVectorClient,
    SearchParams,
    UpsertPayload,
    VectorPoint,
)


def _make_schema(
    *,
    with_sparse: bool = True,
    with_colbert: bool = False,
) -> QdrantCollectionSchema:
    """Build a QdrantCollectionSchema for testing."""
    vectors: dict[str, QdrantVectorDefinition] = {
        "muvera": QdrantVectorDefinition(size=8192, distance="Dot"),
    }
    colbert_name: str | None = None
    if with_colbert:
        vectors["colbert"] = QdrantVectorDefinition(
            size=48,
            distance="Cosine",
            multivector_config={"comparator": "max_sim"},
        )
        colbert_name = "colbert"
    return QdrantCollectionSchema(
        vectors=vectors,
        sparse=QdrantSparseConfig() if with_sparse else None,
        primary_dense_name="muvera",
        colbert_name=colbert_name,
    )


def _make_client(
    schema: QdrantCollectionSchema | None = None,
) -> QdrantVectorClient:
    """Create a QdrantVectorClient with a fake deferred transport."""
    client = QdrantVectorClient(QdrantSettings(), schema or _make_schema())
    client._client_instance = AsyncMock()
    return client


class TestHybridSearchResult:
    """Tests for HybridSearchResult dataclass."""

    def test_init(self) -> None:
        """Test HybridSearchResult initialization."""
        result = HybridSearchResult(
            id="test-id",
            score=0.95,
            payload={"key": "value"},
        )
        assert result.id == "test-id"
        assert abs(result.score - 0.95) < 0.01
        assert result.payload == {"key": "value"}

    def test_is_frozen_dataclass(self) -> None:
        """Test HybridSearchResult is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(HybridSearchResult)
        params = getattr(HybridSearchResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestUpsertPayload:
    """Tests for UpsertPayload dataclass."""

    def test_init_minimal(self) -> None:
        """Test UpsertPayload with minimal args."""
        payload = UpsertPayload(
            entity_id="entity-123",
            entity_type="job",
            collection_version="v1",
            content_hash="abc123",
        )
        assert payload.entity_id == "entity-123"
        assert payload.entity_type == "job"
        assert payload.is_active is True
        assert payload.extra is None

    def test_init_full(self) -> None:
        """Test UpsertPayload with all args."""
        payload = UpsertPayload(
            entity_id="entity-123",
            entity_type="job",
            collection_version="v1",
            content_hash="abc123",
            is_active=False,
            extra={"custom": "data"},
        )
        assert payload.is_active is False
        assert payload.extra == {"custom": "data"}

    def test_to_dict_merges_extra(self) -> None:
        """Test to_dict merges extra fields into the base dict."""
        payload = UpsertPayload(
            entity_id="e-1",
            entity_type="skill",
            collection_version="v2",
            content_hash="h1",
            extra={"skill_name": "Python"},
        )
        result = payload.to_dict()
        assert result["entity_id"] == "e-1"
        assert result["skill_name"] == "Python"

    def test_to_dict_without_extra(self) -> None:
        """Test to_dict without extra returns only base fields."""
        payload = UpsertPayload(
            entity_id="e-2",
            entity_type="job",
            collection_version="v1",
            content_hash="h2",
        )
        result = payload.to_dict()
        assert "skill_name" not in result
        assert set(result.keys()) == {"entity_id", "entity_type", "collection_version", "content_hash", "is_active"}


class TestQdrantVectorClientInit:
    """Tests for QdrantVectorClient construction and schema derivation."""

    def test_schema_required(self) -> None:
        """Test that collection_schema is a required argument."""
        import inspect

        sig = inspect.signature(QdrantVectorClient.__init__)
        param = sig.parameters["collection_schema"]
        assert param.default is inspect.Parameter.empty

    def test_init_with_schema(self) -> None:
        """Test schema-driven client derives vector names from role fields."""
        schema = _make_schema(with_sparse=True, with_colbert=True)
        client = _make_client(schema)
        assert client.primary_dense_name == "muvera"
        assert client.sparse_name == "sparse"
        assert client._colbert_name == "colbert"

    def test_init_schema_no_sparse(self) -> None:
        """Test client without sparse vectors in schema."""
        schema = _make_schema(with_sparse=False)
        client = _make_client(schema)
        assert client.primary_dense_name == "muvera"
        assert client.sparse_name is None

    def test_init_schema_no_colbert(self) -> None:
        """Test client without ColBERT in schema."""
        schema = _make_schema(with_colbert=False)
        client = _make_client(schema)
        assert client._colbert_name is None

    def test_raw_client_property(self) -> None:
        """Test raw_client property."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance
            client = QdrantVectorClient(QdrantSettings(), schema)
            assert client.raw_client is mock_instance


class TestQdrantVectorClient:
    """Tests for QdrantVectorClient search and mutation methods."""

    @pytest.mark.asyncio
    async def test_search_hybrid(self) -> None:
        """Test search_hybrid method."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.id = "point-1"
            mock_point.score = 0.9
            mock_point.payload = {"entity_id": "job-1"}
            mock_instance.query_points.return_value = MagicMock(points=[mock_point])
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = SearchParams(collection_name="jobs_semantic_repr_v1")
            results = await client.search_hybrid(
                query_muvera_fde=[0.1] * 2048,
                query_sparse_indices=[1, 5, 10],
                query_sparse_values=[0.5, 0.3, 0.2],
                params=params,
            )

            assert len(results) == 1
            assert results[0].id == "point-1"
            mock_instance.query_points.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_hybrid_no_sparse_raises(self) -> None:
        """Test search_hybrid raises ValueError when schema has no sparse vectors."""
        schema = _make_schema(with_sparse=False)
        client = _make_client(schema)
        with pytest.raises(ValueError, match="sparse vector"):
            await client.search_hybrid(
                query_muvera_fde=[0.1] * 8192,
                query_sparse_indices=[1],
                query_sparse_values=[0.5],
                params=SearchParams(collection_name="test"),
            )

    @pytest.mark.asyncio
    async def test_search_muvera_only(self) -> None:
        """Test search_muvera_only method."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.id = "point-1"
            mock_point.score = 0.85
            mock_point.payload = {"entity_id": "job-1"}
            mock_response = MagicMock()
            mock_response.points = [mock_point]
            mock_instance.query_points.return_value = mock_response
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            results = await client.search_muvera_only(
                collection_name="jobs_semantic_repr_v1",
                query_muvera_fde=[0.1] * 2048,
            )

            assert len(results) == 1
            assert results[0].id == "point-1"
            mock_instance.query_points.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_dense(self) -> None:
        """Test search_dense method."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.id = "point-1"
            mock_point.score = 0.88
            mock_point.payload = {"name": "Python"}
            mock_response = MagicMock()
            mock_response.points = [mock_point]
            mock_instance.query_points.return_value = mock_response
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = SearchParams(collection_name="skills_collection", limit=5)
            results = await client.search_dense(
                query_vector=[0.1] * 768,
                params=params,
            )

            assert len(results) == 1
            assert results[0].id == "point-1"
            assert abs(results[0].score - 0.88) < 0.01
            mock_instance.query_points.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_dense_batch_empty_returns_empty(self) -> None:
        """Test search_dense_batch returns empty list without calling Qdrant for empty input."""
        schema = _make_schema()
        client = _make_client(schema)
        params = SearchParams(collection_name="skills_collection", limit=5)

        results = await client.search_dense_batch(queries=[], params=params)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_dense_batch_single_qdrant_call(self) -> None:
        """Test search_dense_batch uses one query_batch_points call for multiple queries."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()

            def _make_point(pid: str, score: float) -> MagicMock:
                p = MagicMock()
                p.id = pid
                p.score = score
                p.payload = {"name": pid}
                return p

            resp1 = MagicMock()
            resp1.points = [_make_point("skill-1", 0.9)]
            resp2 = MagicMock()
            resp2.points = [_make_point("skill-2", 0.8), _make_point("skill-3", 0.7)]
            mock_instance.query_batch_points.return_value = [resp1, resp2]
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = SearchParams(collection_name="skills_collection", limit=5)
            queries = [[0.1] * 768, [0.2] * 768]
            results = await client.search_dense_batch(queries=queries, params=params)

        assert len(results) == 2
        assert len(results[0]) == 1
        assert results[0][0].id == "skill-1"
        assert len(results[1]) == 2
        assert results[1][0].id == "skill-2"
        mock_instance.query_batch_points.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_vector_point(self) -> None:
        """Test upsert_vector_point method with a MUVERA embedding."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            payload = UpsertPayload(
                entity_id="job-123",
                entity_type="job",
                collection_version="v1",
                content_hash="hash123",
            )
            point = VectorPoint(
                point_id="point-123",
                embeddings=[
                    EmbeddingVector(
                        embedding_type=EmbeddingType.MUVERA,
                        dense=DenseData(values=[0.1] * 8192),
                        collection_version="v1",
                    )
                ],
                payload=payload,
            )
            await client.upsert_vector_point("jobs_semantic_repr_v1", point)

            mock_instance.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_vector_point_no_sparse_raises(self) -> None:
        """Test upsert_vector_point raises ValueError when schema has no sparse vectors."""
        schema = _make_schema(with_sparse=False)
        client = _make_client(schema)
        payload = UpsertPayload(
            entity_id="job-123",
            entity_type="job",
            collection_version="v1",
            content_hash="hash123",
        )
        point = VectorPoint(
            point_id="point-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.SPARSE,
                    sparse=SparseData(indices=[1], values=[0.5]),
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="sparse vector"):
            await client.upsert_vector_point("test", point)

    @pytest.mark.asyncio
    async def test_upsert_vector_point_dense_no_data_raises(self) -> None:
        """Test upsert raises ValueError when MUVERA embedding has no DenseData."""
        client = _make_client()
        payload = UpsertPayload(
            entity_id="job-1",
            entity_type="job",
            collection_version="v1",
            content_hash="hash",
        )
        point = VectorPoint(
            point_id="point-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.MUVERA,
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="no DenseData"):
            await client.upsert_vector_point("test", point)

    @pytest.mark.asyncio
    async def test_upsert_vector_point_sparse_no_data_raises(self) -> None:
        """Test upsert raises ValueError when SPARSE embedding has no SparseData."""
        client = _make_client()
        payload = UpsertPayload(
            entity_id="job-1",
            entity_type="job",
            collection_version="v1",
            content_hash="hash",
        )
        point = VectorPoint(
            point_id="point-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.SPARSE,
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="no SparseData"):
            await client.upsert_vector_point("test", point)

    @pytest.mark.asyncio
    async def test_upsert_vector_point_sparse_happy_path(self) -> None:
        """Test SPARSE embedding is successfully upserted when schema has sparse slot."""
        schema = _make_schema(with_sparse=True)
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            payload = UpsertPayload(
                entity_id="job-1",
                entity_type="job",
                collection_version="v1",
                content_hash="hash",
            )
            point = VectorPoint(
                point_id="point-1",
                embeddings=[
                    EmbeddingVector(
                        embedding_type=EmbeddingType.SPARSE,
                        sparse=SparseData(indices=[1, 2], values=[0.5, 0.8]),
                        collection_version="v1",
                    )
                ],
                payload=payload,
            )
            await client.upsert_vector_point("test", point)

        mock_instance.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_vector_point_colbert_happy_path(self) -> None:
        """Test COLBERT multi-vector embedding is successfully upserted."""
        schema = _make_schema(with_colbert=True, with_sparse=False)
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            payload = UpsertPayload(
                entity_id="job-1",
                entity_type="job",
                collection_version="v1",
                content_hash="hash",
            )
            num_tokens, token_dim = 3, 4
            point = VectorPoint(
                point_id="point-1",
                embeddings=[
                    EmbeddingVector(
                        embedding_type=EmbeddingType.COLBERT,
                        multi_vector=MultiVectorData(
                            num_tokens=num_tokens,
                            token_dim=token_dim,
                            values=[0.1] * (num_tokens * token_dim),
                        ),
                        collection_version="v1",
                    )
                ],
                payload=payload,
            )
            await client.upsert_vector_point("test", point)

        mock_instance.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_vector_point_colbert_no_data_raises(self) -> None:
        """Test upsert raises ValueError when COLBERT embedding has no MultiVectorData."""
        schema = _make_schema(with_colbert=True, with_sparse=False)
        client = _make_client(schema)
        payload = UpsertPayload(
            entity_id="job-1",
            entity_type="job",
            collection_version="v1",
            content_hash="hash",
        )
        point = VectorPoint(
            point_id="point-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.COLBERT,
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="no MultiVectorData"):
            await client.upsert_vector_point("test", point)

    @pytest.mark.asyncio
    async def test_upsert_vector_point_colbert_no_schema_slot_raises(self) -> None:
        """Test upsert raises ValueError when COLBERT embedding is used but schema has no colbert slot."""
        schema = _make_schema(with_colbert=False, with_sparse=False)
        client = _make_client(schema)
        payload = UpsertPayload(
            entity_id="job-1",
            entity_type="job",
            collection_version="v1",
            content_hash="hash",
        )
        point = VectorPoint(
            point_id="point-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.COLBERT,
                    multi_vector=MultiVectorData(num_tokens=2, token_dim=4, values=[0.1] * 8),
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="no ColBERT vector"):
            await client.upsert_vector_point("test", point)

    @pytest.mark.asyncio
    async def test_upsert_vector_point_unrecognized_type_raises(self) -> None:
        """Test upsert raises ValueError for EmbeddingType.UNSPECIFIED (unhandled case)."""
        client = _make_client()
        payload = UpsertPayload(
            entity_id="job-1",
            entity_type="job",
            collection_version="v1",
            content_hash="hash",
        )
        point = VectorPoint(
            point_id="point-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.UNSPECIFIED,
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="Unrecognized EmbeddingType"):
            await client.upsert_vector_point("test", point)

    @pytest.mark.asyncio
    async def test_upsert_vector_points_batch_empty_returns_zero(self) -> None:
        """Test upsert_vector_points_batch returns 0 immediately for empty list."""
        client = _make_client()
        count = await client.upsert_vector_points_batch("test", points=[])
        assert count == 0

    @pytest.mark.asyncio
    async def test_upsert_vector_points_batch(self) -> None:
        """Test upsert_vector_points_batch method with multiple VectorPoints."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            payload = UpsertPayload(
                entity_id="job-123",
                entity_type="job",
                collection_version="v1",
                content_hash="hash123",
            )
            points = [
                VectorPoint(
                    point_id="point-1",
                    embeddings=[
                        EmbeddingVector(
                            embedding_type=EmbeddingType.MUVERA,
                            dense=DenseData(values=[0.1] * 8192),
                            collection_version="v1",
                        )
                    ],
                    payload=payload,
                ),
                VectorPoint(
                    point_id="point-2",
                    embeddings=[
                        EmbeddingVector(
                            embedding_type=EmbeddingType.MUVERA,
                            dense=DenseData(values=[0.2] * 8192),
                            collection_version="v1",
                        )
                    ],
                    payload=payload,
                ),
            ]
            count = await client.upsert_vector_points_batch(
                collection_name="jobs_semantic_repr_v1",
                points=points,
                batch_size=10,
            )

            assert count == 2
            mock_instance.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_point_found(self) -> None:
        """Test get_point when point exists."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.payload = {"entity_id": "job-123"}
            mock_instance.retrieve.return_value = [mock_point]
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            result = await client.get_point("jobs_semantic_repr_v1", "point-123")

            assert result == {"entity_id": "job-123"}

    @pytest.mark.asyncio
    async def test_get_point_not_found(self) -> None:
        """Test get_point when point doesn't exist."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_instance.retrieve.return_value = []
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            result = await client.get_point("jobs_semantic_repr_v1", "nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_point_exists_true(self) -> None:
        """Test point_exists returns True when point exists."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.payload = {}
            mock_instance.retrieve.return_value = [mock_point]
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            assert await client.point_exists("jobs_semantic_repr_v1", "point-123") is True

    @pytest.mark.asyncio
    async def test_point_exists_false(self) -> None:
        """Test point_exists returns False when point doesn't exist."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_instance.retrieve.return_value = []
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            assert await client.point_exists("jobs_semantic_repr_v1", "nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_points(self) -> None:
        """Test delete_points method."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            await client.delete_points("jobs_semantic_repr_v1", ["point-1", "point-2"])

            mock_instance.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_points_inactive(self) -> None:
        """Test set_points_inactive method."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            await client.set_points_inactive("jobs_semantic_repr_v1", ["point-1", "point-2"])

            mock_instance.set_payload.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_points(self) -> None:
        """Test count_points method."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_instance.count.return_value = MagicMock(count=42)
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            count = await client.count_points("jobs_semantic_repr_v1", filters={"is_active": True})

            assert count == 42
            mock_instance.count.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_grouped(self) -> None:
        """Test search_grouped method with Qdrant native group_by."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()

            mock_hit1 = MagicMock()
            mock_hit1.id = "skill-1_label"
            mock_hit1.score = 0.95
            mock_hit1.payload = {"skill_id": "skill-1", "skill_name": "Python"}

            mock_hit2 = MagicMock()
            mock_hit2.id = "skill-2_label"
            mock_hit2.score = 0.88
            mock_hit2.payload = {"skill_id": "skill-2", "skill_name": "JavaScript"}

            mock_group1 = MagicMock()
            mock_group1.hits = [mock_hit1]

            mock_group2 = MagicMock()
            mock_group2.hits = [mock_hit2]

            mock_instance.query_points_groups.return_value = MagicMock(groups=[mock_group1, mock_group2])
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = GroupedSearchParams(
                collection_name="skills_collection",
                limit=10,
                group_by="skill_id",
                group_size=1,
            )
            results = await client.search_grouped(
                query_vector=[0.1] * 768,
                params=params,
            )

            assert len(results) == 2
            assert results[0].id == "skill-1_label"
            assert abs(results[0].score - 0.95) < 0.01
            assert results[0].payload["skill_name"] == "Python"
            assert results[1].id == "skill-2_label"
            mock_instance.query_points_groups.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_grouped_with_filters(self) -> None:
        """Test search_grouped with filters and score threshold."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_instance.query_points_groups.return_value = MagicMock(groups=[])
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = GroupedSearchParams(
                collection_name="skills_collection",
                limit=5,
                group_by="skill_id",
                group_size=1,
                score_threshold=0.8,
                filters={"is_active": True},
            )
            results = await client.search_grouped(
                query_vector=[0.1] * 768,
                params=params,
            )

            assert len(results) == 0
            mock_instance.query_points_groups.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_grouped_with_named_vector(self) -> None:
        """Test search_grouped with explicit named vector overrides schema default."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_instance.query_points_groups.return_value = MagicMock(groups=[])
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = GroupedSearchParams(
                collection_name="skills_collection",
                limit=10,
                group_by="skill_id",
                vector_name="custom_vector",
            )
            await client.search_grouped(
                query_vector=[0.1] * 768,
                params=params,
            )

            call_kwargs = mock_instance.query_points_groups.call_args
            assert call_kwargs.kwargs["using"] == "custom_vector"

    @pytest.mark.asyncio
    async def test_search_grouped_multiple_hits_per_group(self) -> None:
        """Test search_grouped with multiple hits per group (group_size > 1)."""
        schema = _make_schema()
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()

            mock_hit1 = MagicMock()
            mock_hit1.id = "skill-1_label"
            mock_hit1.score = 0.95
            mock_hit1.payload = {"skill_id": "skill-1", "embedding_source": "label"}

            mock_hit2 = MagicMock()
            mock_hit2.id = "skill-1_description"
            mock_hit2.score = 0.90
            mock_hit2.payload = {"skill_id": "skill-1", "embedding_source": "description"}

            mock_group = MagicMock()
            mock_group.hits = [mock_hit1, mock_hit2]

            mock_instance.query_points_groups.return_value = MagicMock(groups=[mock_group])
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), schema)
            params = GroupedSearchParams(
                collection_name="skills_collection",
                limit=10,
                group_by="skill_id",
                group_size=3,
            )
            results = await client.search_grouped(
                query_vector=[0.1] * 768,
                params=params,
            )

            assert len(results) == 2
            assert results[0].payload["embedding_source"] == "label"
            assert results[1].payload["embedding_source"] == "description"

    @pytest.mark.asyncio
    async def test_upsert_vector_points_batch_no_sparse_raises(self) -> None:
        """Test upsert_vector_points_batch raises ValueError when schema has no sparse vectors."""
        schema = _make_schema(with_sparse=False)
        client = _make_client(schema)
        payload = UpsertPayload(
            entity_id="job-1",
            entity_type="job",
            collection_version="v1",
            content_hash="hash",
        )
        point = VectorPoint(
            point_id="p-1",
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.SPARSE,
                    sparse=SparseData(indices=[1], values=[0.5]),
                    collection_version="v1",
                )
            ],
            payload=payload,
        )
        with pytest.raises(ValueError, match="sparse vector"):
            await client.upsert_vector_points_batch(
                collection_name="test",
                points=[point],
            )

    @pytest.mark.asyncio
    async def test_get_points_batch_empty_returns_empty(self) -> None:
        """Test get_points_batch returns empty dict immediately for empty input."""
        client = _make_client()
        result = await client.get_points_batch("col", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_points_batch_retrieves_payloads(self) -> None:
        """Test get_points_batch returns payload dicts keyed by point id."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.id = "point-abc"
            mock_point.payload = {"entity_id": "job-1"}
            mock_instance.retrieve.return_value = [mock_point]
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            result = await client.get_points_batch("col", ["point-abc"])

        assert result == {"point-abc": {"entity_id": "job-1"}}
        mock_instance.retrieve.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_vectors_empty_returns_empty(self) -> None:
        """Test retrieve_vectors returns empty dict immediately for empty point_ids."""
        client = _make_client()
        result = await client.retrieve_vectors("col", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_retrieve_vectors_returns_dense_vectors(self) -> None:
        """Test retrieve_vectors maps point ids to their dense vector data."""
        with patch("nohiki_qdrant_client.client.create_async_qdrant_client") as mock_qdrant:
            mock_instance = AsyncMock()
            mock_point = MagicMock()
            mock_point.id = "skill-1_label"
            mock_point.vector = [0.5] * 768
            mock_instance.retrieve.return_value = [mock_point]
            mock_qdrant.return_value = mock_instance

            client = QdrantVectorClient(QdrantSettings(), _make_schema())
            result = await client.retrieve_vectors("skills_v1", ["skill-1_label"])

        assert "skill-1_label" in result
        assert len(result["skill-1_label"]) == 768


class TestExtractVector:
    """Tests for QdrantVectorClient._extract_vector static method."""

    def test_dict_input_named_vector(self) -> None:
        """Test extracting a named vector from a dict of vectors."""
        vectors = {"dense": [0.1, 0.2, 0.3], "sparse": [0.9]}
        result = QdrantVectorClient._extract_vector(vectors, "dense")
        assert result == [0.1, 0.2, 0.3]

    def test_dict_input_missing_key_returns_none(self) -> None:
        """Test that a missing key in dict returns None."""
        vectors = {"dense": [0.1]}
        result = QdrantVectorClient._extract_vector(vectors, "colbert")
        assert result is None

    def test_list_input_returns_directly(self) -> None:
        """Test that a plain list is returned as-is (unnamed dense vector)."""
        vector = [0.4, 0.5, 0.6]
        result = QdrantVectorClient._extract_vector(vector, None)
        assert result == [0.4, 0.5, 0.6]

    def test_unknown_type_returns_none(self) -> None:
        """Test that an unrecognised type returns None."""
        result = QdrantVectorClient._extract_vector(None, "dense")
        assert result is None

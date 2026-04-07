"""Tests for multivector module (ColBERT MaxSim reranking)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_qdrant_client.multivector import (
    DISTANCE_METRICS,
    MultiStageQuery,
    MultiStageSearchResult,
    MultiVectorCollectionConfig,
    MultiVectorPoint,
    MuveraMaxSimQuery,
    create_multivector_collection,
    search_multistage,
    search_muvera_then_maxsim,
    upsert_multivector_point,
)
from qdrant_client import models


class TestMultiVectorCollectionConfig:
    """Tests for MultiVectorCollectionConfig dataclass."""

    def test_required_fields(self) -> None:
        """Test config with required fields only."""
        config = MultiVectorCollectionConfig(
            semantic_repr_id="test.v1",
            entity_type="jobs",
            muvera_dim=2048,
            colbert_dim=128,
        )
        assert config.semantic_repr_id == "test.v1"
        assert config.entity_type == "jobs"
        assert config.muvera_dim == 2048
        assert config.colbert_dim == 128

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = MultiVectorCollectionConfig(
            semantic_repr_id="test.v1",
            entity_type="jobs",
            muvera_dim=2048,
            colbert_dim=128,
        )
        assert config.distance_metric == "Dot"
        assert config.alias_name is None
        assert config.on_disk is True
        assert config.hnsw_m == 16
        assert config.hnsw_ef_construct == 100
        assert config.colbert_on_disk is True

    def test_custom_values(self) -> None:
        """Test config with custom values."""
        config = MultiVectorCollectionConfig(
            semantic_repr_id="test.v1",
            entity_type="profiles",
            muvera_dim=8192,
            colbert_dim=48,
            distance_metric="Cosine",
            alias_name="profiles_active",
            on_disk=False,
            hnsw_m=32,
            hnsw_ef_construct=200,
            colbert_on_disk=False,
        )
        assert config.distance_metric == "Cosine"
        assert config.alias_name == "profiles_active"
        assert config.on_disk is False
        assert config.hnsw_m == 32
        assert config.hnsw_ef_construct == 200
        assert config.colbert_on_disk is False

    def test_is_frozen_dataclass(self) -> None:
        """Test that config is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(MultiVectorCollectionConfig)
        params = getattr(MultiVectorCollectionConfig, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestMultiStageSearchResult:
    """Tests for MultiStageSearchResult dataclass."""

    def test_fields(self) -> None:
        """Test result fields."""
        result = MultiStageSearchResult(
            id="point-123",
            muvera_score=0.85,
            maxsim_score=0.92,
            payload={"title": "Software Engineer"},
        )
        assert result.id == "point-123"
        assert abs(result.muvera_score - 0.85) < 1e-9
        assert abs(result.maxsim_score - 0.92) < 1e-9
        assert result.payload == {"title": "Software Engineer"}

    def test_is_frozen_dataclass(self) -> None:
        """Test that result is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(MultiStageSearchResult)
        params = getattr(MultiStageSearchResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestMultiVectorPoint:
    """Tests for MultiVectorPoint dataclass."""

    def test_fields(self) -> None:
        """Test point fields."""
        point = MultiVectorPoint(
            point_id="doc-123",
            muvera_fde=[0.1, 0.2, 0.3],
            sparse_indices=[1, 5, 10],
            sparse_values=[0.5, 0.3, 0.2],
            colbert_tokens=[[0.1, 0.2], [0.3, 0.4]],
            payload={"type": "job"},
        )
        assert point.point_id == "doc-123"
        assert point.muvera_fde == [0.1, 0.2, 0.3]
        assert point.sparse_indices == [1, 5, 10]
        assert point.sparse_values == [0.5, 0.3, 0.2]
        assert point.colbert_tokens == [[0.1, 0.2], [0.3, 0.4]]
        assert point.payload == {"type": "job"}

    def test_is_frozen_dataclass(self) -> None:
        """Test that point is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(MultiVectorPoint)
        params = getattr(MultiVectorPoint, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestMultiStageQuery:
    """Tests for MultiStageQuery dataclass."""

    def test_required_fields(self) -> None:
        """Test query with required fields."""
        query = MultiStageQuery(
            muvera_fde=[0.1, 0.2],
            colbert_tokens=[[0.1, 0.2]],
            sparse_indices=[1, 2],
            sparse_values=[0.5, 0.5],
        )
        assert query.muvera_fde == [0.1, 0.2]
        assert query.colbert_tokens == [[0.1, 0.2]]
        assert query.sparse_indices == [1, 2]
        assert query.sparse_values == [0.5, 0.5]

    def test_default_values(self) -> None:
        """Test default query values."""
        query = MultiStageQuery(
            muvera_fde=[0.1],
            colbert_tokens=[[0.1]],
            sparse_indices=[1],
            sparse_values=[0.5],
        )
        assert query.prefetch_limit == 200
        assert query.final_limit == 50
        assert query.filters is None
        assert query.score_threshold is None

    def test_custom_values(self) -> None:
        """Test query with custom values."""
        query = MultiStageQuery(
            muvera_fde=[0.1],
            colbert_tokens=[[0.1]],
            sparse_indices=[1],
            sparse_values=[0.5],
            prefetch_limit=500,
            final_limit=100,
            filters={"is_active": True},
            score_threshold=0.5,
        )
        assert query.prefetch_limit == 500
        assert query.final_limit == 100
        assert query.filters == {"is_active": True}
        assert query.score_threshold is not None
        assert abs(query.score_threshold - 0.5) < 1e-9


class TestMuveraMaxSimQuery:
    """Tests for MuveraMaxSimQuery dataclass."""

    def test_required_fields(self) -> None:
        """Test query with required fields."""
        query = MuveraMaxSimQuery(
            muvera_fde=[0.1, 0.2],
            colbert_tokens=[[0.1, 0.2]],
        )
        assert query.muvera_fde == [0.1, 0.2]
        assert query.colbert_tokens == [[0.1, 0.2]]

    def test_default_values(self) -> None:
        """Test default query values."""
        query = MuveraMaxSimQuery(
            muvera_fde=[0.1],
            colbert_tokens=[[0.1]],
        )
        assert query.prefetch_limit == 200
        assert query.final_limit == 50
        assert query.filters is None

    def test_custom_values(self) -> None:
        """Test query with custom values."""
        query = MuveraMaxSimQuery(
            muvera_fde=[0.1],
            colbert_tokens=[[0.1]],
            prefetch_limit=300,
            final_limit=75,
            filters={"company": "Acme"},
        )
        assert query.prefetch_limit == 300
        assert query.final_limit == 75
        assert query.filters == {"company": "Acme"}


class TestDistanceMetrics:
    """Tests for DISTANCE_METRICS constant."""

    def test_dot_metric(self) -> None:
        """Test Dot distance metric mapping."""
        assert DISTANCE_METRICS["Dot"] == models.Distance.DOT

    def test_cosine_metric(self) -> None:
        """Test Cosine distance metric mapping."""
        assert DISTANCE_METRICS["Cosine"] == models.Distance.COSINE

    def test_euclid_metric(self) -> None:
        """Test Euclid distance metric mapping."""
        assert DISTANCE_METRICS["Euclid"] == models.Distance.EUCLID

    def test_all_metrics_present(self) -> None:
        """Test all expected metrics are present."""
        assert len(DISTANCE_METRICS) == 3


class TestCreateMultivectorCollection:
    """Tests for create_multivector_collection function."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create mock async Qdrant client."""
        client = AsyncMock()
        client.recreate_collection = AsyncMock()
        client.create_payload_index = AsyncMock()
        return client

    @pytest.fixture
    def collection_config(self) -> MultiVectorCollectionConfig:
        """Create test collection config."""
        return MultiVectorCollectionConfig(
            semantic_repr_id="test.semantic_repr.v1",
            entity_type="jobs",
            muvera_dim=2048,
            colbert_dim=128,
        )

    @pytest.mark.asyncio
    async def test_creates_collection(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test collection creation."""
        result = await create_multivector_collection(mock_client, collection_config)

        assert result == "jobs_test_semantic_repr_v1"
        mock_client.recreate_collection.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_payload_indexes(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test payload index creation."""
        await create_multivector_collection(mock_client, collection_config)

        assert mock_client.create_payload_index.call_count > 0

    @pytest.mark.asyncio
    async def test_creates_alias_when_specified(
        self,
        mock_client: AsyncMock,
    ) -> None:
        """Test alias creation when specified."""
        config = MultiVectorCollectionConfig(
            semantic_repr_id="test.v1",
            entity_type="jobs",
            muvera_dim=2048,
            colbert_dim=128,
            alias_name="jobs_active",
        )

        with patch("nohiki_qdrant_client.multivector._create_or_update_alias_async") as mock_alias:
            mock_alias.return_value = None
            await create_multivector_collection(mock_client, config)
            mock_alias.assert_called_once()

    @pytest.mark.asyncio
    async def test_vector_config_includes_muvera(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test MUVERA vector configuration."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        assert "muvera" in call_kwargs["vectors_config"]

    @pytest.mark.asyncio
    async def test_vector_config_includes_colbert(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test ColBERT multi-vector configuration."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        assert "colbert" in call_kwargs["vectors_config"]

    @pytest.mark.asyncio
    async def test_sparse_vector_config(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test sparse vector configuration."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        assert "sparse" in call_kwargs["sparse_vectors_config"]

    @pytest.mark.asyncio
    async def test_colbert_uses_cosine_distance(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test ColBERT vector always uses COSINE distance regardless of config."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        colbert_config = call_kwargs["vectors_config"]["colbert"]
        assert colbert_config.distance == models.Distance.COSINE

    @pytest.mark.asyncio
    async def test_muvera_uses_configured_distance(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test MUVERA vector uses configured distance (default DOT)."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        muvera_config = call_kwargs["vectors_config"]["muvera"]
        assert muvera_config.distance == models.Distance.DOT

    @pytest.mark.asyncio
    async def test_colbert_hnsw_disabled(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test ColBERT has HNSW disabled (m=0) since it's only for reranking."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        colbert_config = call_kwargs["vectors_config"]["colbert"]
        assert colbert_config.hnsw_config is not None
        assert colbert_config.hnsw_config.m == 0

    @pytest.mark.asyncio
    async def test_colbert_has_multivector_maxsim(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test ColBERT has multivector_config with MAX_SIM comparator."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        colbert_config = call_kwargs["vectors_config"]["colbert"]
        assert colbert_config.multivector_config is not None
        assert colbert_config.multivector_config.comparator == models.MultiVectorComparator.MAX_SIM

    @pytest.mark.asyncio
    async def test_muvera_has_hnsw_configured(
        self,
        mock_client: AsyncMock,
        collection_config: MultiVectorCollectionConfig,
    ) -> None:
        """Test MUVERA has HNSW properly configured for ANN search."""
        await create_multivector_collection(mock_client, collection_config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        muvera_config = call_kwargs["vectors_config"]["muvera"]
        assert muvera_config.hnsw_config is not None
        assert muvera_config.hnsw_config.m == collection_config.hnsw_m
        assert muvera_config.hnsw_config.ef_construct == collection_config.hnsw_ef_construct

    @pytest.mark.asyncio
    async def test_colbert_ignores_config_distance_metric(
        self,
        mock_client: AsyncMock,
    ) -> None:
        """Test ColBERT uses COSINE even when config specifies different distance."""
        config = MultiVectorCollectionConfig(
            semantic_repr_id="test.v1",
            entity_type="jobs",
            muvera_dim=2048,
            colbert_dim=128,
            distance_metric="Euclid",
        )

        await create_multivector_collection(mock_client, config)

        call_kwargs = mock_client.recreate_collection.call_args[1]
        colbert_config = call_kwargs["vectors_config"]["colbert"]
        muvera_config = call_kwargs["vectors_config"]["muvera"]

        # ColBERT always uses COSINE
        assert colbert_config.distance == models.Distance.COSINE
        # MUVERA uses configured distance
        assert muvera_config.distance == models.Distance.EUCLID


class TestUpsertMultivectorPoint:
    """Tests for upsert_multivector_point function."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create mock async Qdrant client."""
        client = AsyncMock()
        client.upsert = AsyncMock()
        return client

    @pytest.fixture
    def point_data(self) -> MultiVectorPoint:
        """Create test point data."""
        return MultiVectorPoint(
            point_id="doc-123",
            muvera_fde=[0.1] * 2048,
            sparse_indices=[1, 5, 10],
            sparse_values=[0.5, 0.3, 0.2],
            colbert_tokens=[[0.1] * 128 for _ in range(50)],
            payload={"title": "Software Engineer", "is_active": True},
        )

    @pytest.mark.asyncio
    async def test_upserts_point(
        self,
        mock_client: AsyncMock,
        point_data: MultiVectorPoint,
    ) -> None:
        """Test point upsert."""
        await upsert_multivector_point(mock_client, "jobs_active", point_data)

        mock_client.upsert.assert_called_once()
        call_kwargs = mock_client.upsert.call_args[1]
        assert call_kwargs["collection_name"] == "jobs_active"
        assert len(call_kwargs["points"]) == 1

    @pytest.mark.asyncio
    async def test_point_contains_all_vectors(
        self,
        mock_client: AsyncMock,
        point_data: MultiVectorPoint,
    ) -> None:
        """Test point contains all vector types."""
        await upsert_multivector_point(mock_client, "jobs_active", point_data)

        call_kwargs = mock_client.upsert.call_args[1]
        point = call_kwargs["points"][0]
        assert "muvera" in point.vector
        assert "colbert" in point.vector
        assert "sparse" in point.vector

    @pytest.mark.asyncio
    async def test_point_contains_payload(
        self,
        mock_client: AsyncMock,
        point_data: MultiVectorPoint,
    ) -> None:
        """Test point contains payload."""
        await upsert_multivector_point(mock_client, "jobs_active", point_data)

        call_kwargs = mock_client.upsert.call_args[1]
        point = call_kwargs["points"][0]
        assert point.payload == point_data.payload


class TestSearchMultistage:
    """Tests for search_multistage function."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create mock async Qdrant client."""
        client = AsyncMock()

        mock_point = MagicMock()
        mock_point.id = "result-1"
        mock_point.score = 0.95
        mock_point.payload = {"title": "Engineer"}

        mock_results = MagicMock()
        mock_results.points = [mock_point]

        client.query_points = AsyncMock(return_value=mock_results)
        return client

    @pytest.fixture
    def search_query(self) -> MultiStageQuery:
        """Create test search query."""
        return MultiStageQuery(
            muvera_fde=[0.1] * 2048,
            colbert_tokens=[[0.1] * 128 for _ in range(32)],
            sparse_indices=[1, 5, 10],
            sparse_values=[0.5, 0.3, 0.2],
            prefetch_limit=200,
            final_limit=50,
        )

    @pytest.mark.asyncio
    async def test_returns_results(
        self,
        mock_client: AsyncMock,
        search_query: MultiStageQuery,
    ) -> None:
        """Test search returns results."""
        results = await search_multistage(mock_client, "jobs_active", search_query)

        assert len(results) == 1
        assert isinstance(results[0], MultiStageSearchResult)

    @pytest.mark.asyncio
    async def test_result_fields(
        self,
        mock_client: AsyncMock,
        search_query: MultiStageQuery,
    ) -> None:
        """Test result field values."""
        results = await search_multistage(mock_client, "jobs_active", search_query)

        assert results[0].id == "result-1"
        assert abs(results[0].maxsim_score - 0.95) < 1e-9
        assert results[0].payload == {"title": "Engineer"}

    @pytest.mark.asyncio
    async def test_uses_prefetch(
        self,
        mock_client: AsyncMock,
        search_query: MultiStageQuery,
    ) -> None:
        """Test search uses prefetch for multi-stage."""
        await search_multistage(mock_client, "jobs_active", search_query)

        # Get the first call (main query)
        call_kwargs = mock_client.query_points.call_args_list[0][1]
        assert "prefetch" in call_kwargs
        assert len(call_kwargs["prefetch"]) == 2

    @pytest.mark.asyncio
    async def test_uses_colbert_for_final_query(
        self,
        mock_client: AsyncMock,
        search_query: MultiStageQuery,
    ) -> None:
        """Test ColBERT is used for final reranking."""
        await search_multistage(mock_client, "jobs_active", search_query)

        # Get the first call (main query)
        call_kwargs = mock_client.query_points.call_args_list[0][1]
        assert call_kwargs["using"] == "colbert"

    @pytest.mark.asyncio
    async def test_applies_filters(
        self,
        mock_client: AsyncMock,
    ) -> None:
        """Test filters are applied."""
        query = MultiStageQuery(
            muvera_fde=[0.1],
            colbert_tokens=[[0.1]],
            sparse_indices=[1],
            sparse_values=[0.5],
            filters={"is_active": True},
        )

        await search_multistage(mock_client, "jobs_active", query)

        # Get the first call (main query)
        call_kwargs = mock_client.query_points.call_args_list[0][1]
        prefetch = call_kwargs["prefetch"]
        assert prefetch[0].filter is not None

    @pytest.mark.asyncio
    async def test_handles_empty_results(
        self,
        mock_client: AsyncMock,
        search_query: MultiStageQuery,
    ) -> None:
        """Test handling of empty results."""
        mock_results = MagicMock()
        mock_results.points = []
        mock_client.query_points.return_value = mock_results

        results = await search_multistage(mock_client, "jobs_active", search_query)

        assert results == []


class TestSearchMuveraThenMaxsim:
    """Tests for search_muvera_then_maxsim function."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """Create mock async Qdrant client."""
        client = AsyncMock()

        mock_point = MagicMock()
        mock_point.id = "result-1"
        mock_point.score = 0.90
        mock_point.payload = {"title": "Developer"}

        mock_results = MagicMock()
        mock_results.points = [mock_point]

        client.query_points = AsyncMock(return_value=mock_results)
        return client

    @pytest.fixture
    def search_query(self) -> MuveraMaxSimQuery:
        """Create test search query."""
        return MuveraMaxSimQuery(
            muvera_fde=[0.1] * 2048,
            colbert_tokens=[[0.1] * 128 for _ in range(32)],
            prefetch_limit=200,
            final_limit=50,
        )

    @pytest.mark.asyncio
    async def test_returns_results(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test search returns results."""
        results = await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        assert len(results) == 1
        assert isinstance(results[0], MultiStageSearchResult)

    @pytest.mark.asyncio
    async def test_result_fields(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test result field values."""
        results = await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        assert results[0].id == "result-1"
        assert abs(results[0].maxsim_score - 0.90) < 1e-9
        assert results[0].payload == {"title": "Developer"}

    @pytest.mark.asyncio
    async def test_uses_single_prefetch(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test search uses single MUVERA prefetch."""
        await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        # Get the second call (maxsim query with prefetch)
        call_kwargs = mock_client.query_points.call_args_list[1][1]
        assert "prefetch" in call_kwargs
        assert isinstance(call_kwargs["prefetch"], models.Prefetch)

    @pytest.mark.asyncio
    async def test_uses_colbert_for_final_query(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test ColBERT is used for final reranking."""
        await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        # Get the second call (maxsim query)
        call_kwargs = mock_client.query_points.call_args_list[1][1]
        assert call_kwargs["using"] == "colbert"

    @pytest.mark.asyncio
    async def test_applies_filters(
        self,
        mock_client: AsyncMock,
    ) -> None:
        """Test filters are applied."""
        query = MuveraMaxSimQuery(
            muvera_fde=[0.1],
            colbert_tokens=[[0.1]],
            filters={"company": "Acme"},
        )

        await search_muvera_then_maxsim(mock_client, "jobs_active", query)

        # Get the second call (maxsim query with prefetch)
        call_kwargs = mock_client.query_points.call_args_list[1][1]
        prefetch = call_kwargs["prefetch"]
        assert prefetch.filter is not None

    @pytest.mark.asyncio
    async def test_handles_empty_results(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test handling of empty results."""
        mock_results = MagicMock()
        mock_results.points = []
        mock_client.query_points.return_value = mock_results

        results = await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        assert results == []

    @pytest.mark.asyncio
    async def test_handles_none_payload(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test handling of None payload in results."""
        mock_point = MagicMock()
        mock_point.id = "result-1"
        mock_point.score = 0.90
        mock_point.payload = None

        mock_results = MagicMock()
        mock_results.points = [mock_point]
        mock_client.query_points.return_value = mock_results

        results = await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        assert results[0].payload == {}

    @pytest.mark.asyncio
    async def test_handles_none_score(
        self,
        mock_client: AsyncMock,
        search_query: MuveraMaxSimQuery,
    ) -> None:
        """Test handling of None score in results."""
        mock_point = MagicMock()
        mock_point.id = "result-1"
        mock_point.score = None
        mock_point.payload = {}

        mock_results = MagicMock()
        mock_results.points = [mock_point]
        mock_client.query_points.return_value = mock_results

        results = await search_muvera_then_maxsim(mock_client, "jobs_active", search_query)

        assert abs(results[0].maxsim_score - 0.0) < 1e-9

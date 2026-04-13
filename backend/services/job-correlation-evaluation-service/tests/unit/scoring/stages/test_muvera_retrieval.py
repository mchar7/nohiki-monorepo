"""Unit tests for MUVERA retrieval stage."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from job_correlation_evaluation_service.services.scoring.stages.muvera_retrieval import (
    DEFAULT_STAGE1_LIMIT,
    MuveraRetrievalStage,
    RetrievalCandidate,
    RetrievalQuery,
)


class TestRetrievalQuery:
    """Tests for RetrievalQuery dataclass."""

    def test_creates_query_with_required_fields(self) -> None:
        """Test query creation with required fields."""
        query = RetrievalQuery(
            muvera_fde=[0.1, 0.2, 0.3],
            sparse_indices=[1, 2, 3],
            sparse_values=[0.5, 0.6, 0.7],
        )
        assert query.muvera_fde == [0.1, 0.2, 0.3]
        assert query.sparse_indices == [1, 2, 3]
        assert query.sparse_values == [0.5, 0.6, 0.7]
        assert query.filters is None
        assert query.limit is None

    def test_creates_query_with_optional_fields(self) -> None:
        """Test query creation with optional fields."""
        query = RetrievalQuery(
            muvera_fde=[0.1],
            sparse_indices=[1],
            sparse_values=[0.5],
            filters={"user_id": "123"},
            limit=500,
            score_threshold=0.5,
        )
        assert query.filters == {"user_id": "123"}
        assert query.limit == 500
        assert query.score_threshold == pytest.approx(0.5)


class TestRetrievalCandidate:
    """Tests for RetrievalCandidate dataclass."""

    def test_creates_candidate(self) -> None:
        """Test candidate creation."""
        candidate = RetrievalCandidate(
            entity_id="job-123",
            muvera_score=0.85,
            payload={"title": "Software Engineer"},
        )
        assert candidate.entity_id == "job-123"
        assert candidate.muvera_score == pytest.approx(0.85)
        assert candidate.payload == {"title": "Software Engineer"}


class TestMuveraRetrievalStage:
    """Tests for MuveraRetrievalStage class."""

    @pytest.fixture
    def mock_qdrant(self) -> AsyncMock:
        """Create mock Qdrant client."""
        return AsyncMock()

    @pytest.fixture
    def stage(self, mock_qdrant: AsyncMock) -> MuveraRetrievalStage:
        """Create retrieval stage."""
        return MuveraRetrievalStage(
            qdrant_client=mock_qdrant,
            collection_name="test-collection",
            default_limit=1000,
        )

    def test_initializes_with_config(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test stage initializes with config."""
        assert stage._qdrant is mock_qdrant
        assert stage._collection_name == "test-collection"
        assert stage._default_limit == 1000

    def test_default_stage1_limit_constant(self) -> None:
        """Test default limit constant."""
        assert DEFAULT_STAGE1_LIMIT == 1000

    @pytest.mark.asyncio
    async def test_retrieve_with_hybrid_search(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve uses hybrid search when sparse vectors available."""
        mock_result = MagicMock()
        mock_result.id = "job-123"
        mock_result.score = 0.85
        mock_result.payload = {"title": "Engineer"}
        mock_qdrant.search_hybrid.return_value = [mock_result]

        query = RetrievalQuery(
            muvera_fde=[0.1, 0.2],
            sparse_indices=[1, 2],
            sparse_values=[0.5, 0.6],
        )

        result = await stage.retrieve(query)

        assert len(result) == 1
        assert result[0].entity_id == "job-123"
        assert result[0].muvera_score == pytest.approx(0.85)
        mock_qdrant.search_hybrid.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrieve_with_muvera_only(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve falls back to MUVERA-only when no sparse vectors."""
        mock_result = MagicMock()
        mock_result.id = "job-456"
        mock_result.score = 0.75
        mock_result.payload = {"title": "Developer"}
        mock_qdrant.search_muvera_only.return_value = [mock_result]

        query = RetrievalQuery(
            muvera_fde=[0.1, 0.2],
            sparse_indices=[],
            sparse_values=[],
        )

        result = await stage.retrieve(query)

        assert len(result) == 1
        assert result[0].entity_id == "job-456"
        mock_qdrant.search_muvera_only.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrieve_uses_query_limit(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve uses query limit when provided."""
        mock_qdrant.search_hybrid.return_value = []

        query = RetrievalQuery(
            muvera_fde=[0.1],
            sparse_indices=[1],
            sparse_values=[0.5],
            limit=100,
        )

        await stage.retrieve(query)

        call_kwargs = mock_qdrant.search_hybrid.call_args.kwargs
        assert call_kwargs["params"].limit == 100

    @pytest.mark.asyncio
    async def test_retrieve_uses_default_limit(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve uses default limit when not in query."""
        mock_qdrant.search_hybrid.return_value = []

        query = RetrievalQuery(
            muvera_fde=[0.1],
            sparse_indices=[1],
            sparse_values=[0.5],
        )

        await stage.retrieve(query)

        call_kwargs = mock_qdrant.search_hybrid.call_args.kwargs
        assert call_kwargs["params"].limit == 1000

    @pytest.mark.asyncio
    async def test_retrieve_passes_filters(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve passes filters to search."""
        mock_qdrant.search_hybrid.return_value = []

        query = RetrievalQuery(
            muvera_fde=[0.1],
            sparse_indices=[1],
            sparse_values=[0.5],
            filters={"status": "active"},
        )

        await stage.retrieve(query)

        call_kwargs = mock_qdrant.search_hybrid.call_args.kwargs
        assert call_kwargs["params"].filters == {"status": "active"}

    @pytest.mark.asyncio
    async def test_retrieve_by_ids_empty(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve_by_ids returns empty dict for empty input."""
        result = await stage.retrieve_by_ids([])
        assert result == {}

    @pytest.mark.asyncio
    async def test_retrieve_by_ids_fetches_payloads(self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock) -> None:
        """Test retrieve_by_ids fetches payloads via single batch call."""
        mock_qdrant.get_points_batch.return_value = {
            "id1": {"title": "Job 1"},
            "id2": {"title": "Job 2"},
        }

        result = await stage.retrieve_by_ids(["id1", "id2"])

        assert len(result) == 2
        assert result["id1"] == {"title": "Job 1"}
        assert result["id2"] == {"title": "Job 2"}
        mock_qdrant.get_points_batch.assert_called_once_with("test-collection", ["id1", "id2"])

    @pytest.mark.asyncio
    async def test_retrieve_by_ids_filters_missing_points(
        self, stage: MuveraRetrievalStage, mock_qdrant: AsyncMock
    ) -> None:
        """Test retrieve_by_ids omits missing points (handled by batch API)."""
        mock_qdrant.get_points_batch.return_value = {
            "id1": {"title": "Job 1"},
        }

        result = await stage.retrieve_by_ids(["id1", "id2"])

        assert len(result) == 1
        assert "id1" in result
        assert "id2" not in result

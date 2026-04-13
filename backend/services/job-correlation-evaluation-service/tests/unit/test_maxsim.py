"""Unit tests for Native MaxSim Stage (Qdrant multi-vector MaxSim)."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
    MaxSimNormalizationParams,
    NativeMaxSimCandidate,
    NativeMaxSimQuery,
    NativeMaxSimQueryParams,
    NativeMaxSimStage,
    build_native_maxsim_query,
)

DEFAULT_NORM_PARAMS = MaxSimNormalizationParams(
    per_token_mean=0.9355,
    per_token_std=0.0396,
)


class TestNativeMaxSimQuery:
    """Tests for NativeMaxSimQuery dataclass."""

    def test_create_query_with_all_fields(self) -> None:
        """Test creating query with all required fields."""
        query = NativeMaxSimQuery(
            muvera_fde=[0.1] * 2048,
            colbert_tokens=[[0.1] * 48 for _ in range(10)],
            sparse_indices=[1, 5, 10],
            sparse_values=[0.5, 0.3, 0.2],
            filters={"is_active": True},
            prefetch_limit=200,
            final_limit=50,
        )

        assert len(query.muvera_fde) == 2048
        assert len(query.colbert_tokens) == 10
        assert query.prefetch_limit == 200
        assert query.final_limit == 50
        assert query.filters == {"is_active": True}

    def test_query_defaults(self) -> None:
        """Test query with default values."""
        query = NativeMaxSimQuery(
            muvera_fde=[0.1] * 100,
            colbert_tokens=[[0.1] * 48],
            sparse_indices=[],
            sparse_values=[],
        )

        assert query.prefetch_limit == 200
        assert query.final_limit == 50
        assert query.filters is None

    def test_query_is_frozen_dataclass(self) -> None:
        """Test that query is a frozen dataclass."""
        assert dataclasses.is_dataclass(NativeMaxSimQuery)
        params = getattr(NativeMaxSimQuery, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestNativeMaxSimCandidate:
    """Tests for NativeMaxSimCandidate dataclass."""

    def test_create_candidate(self) -> None:
        """Test creating a candidate."""
        candidate = NativeMaxSimCandidate(
            entity_id="job-123",
            maxsim_score=12.5,
            payload={"title": "Software Engineer"},
        )

        assert candidate.entity_id == "job-123"
        assert candidate.maxsim_score == pytest.approx(12.5)
        assert candidate.payload == {"title": "Software Engineer"}

    def test_has_maxsim_true(self) -> None:
        """Test has_maxsim property returns True when score > 0."""
        candidate = NativeMaxSimCandidate(
            entity_id="job-1",
            maxsim_score=10.0,
            payload={},
        )

        assert candidate.has_maxsim is True

    def test_has_maxsim_false(self) -> None:
        """Test has_maxsim property returns False when score = 0."""
        candidate = NativeMaxSimCandidate(
            entity_id="job-1",
            maxsim_score=0.0,
            payload={},
        )

        assert candidate.has_maxsim is False

    def test_from_results_batch(self) -> None:
        """Test creating candidates from batch with absolute normalization."""
        from nohiki_qdrant_client import MultiStageSearchResult

        # Use realistic raw MaxSim scores for 1 token (expected ~0.9355 per token)
        # Score > expected -> normalized > 0.5, score < expected -> normalized < 0.5
        results = [
            MultiStageSearchResult(
                id="job-456",
                muvera_score=0.9,
                maxsim_score=0.98,  # Above expected -> high normalized score
                payload={"company": "TechCorp"},
            ),
            MultiStageSearchResult(
                id="job-789",
                muvera_score=0.7,
                maxsim_score=0.85,  # Below expected -> lower normalized score
                payload={"company": "OtherCorp"},
            ),
        ]

        candidates = NativeMaxSimCandidate.from_results_batch(
            results,
            num_tokens=1,
            per_token_mean=0.9355,
            per_token_std=0.0396,
        )

        assert len(candidates) == 2
        assert candidates[0].entity_id == "job-456"
        # Absolute normalization: 0.98 is above expected (0.9355) -> high score
        assert candidates[0].maxsim_score > 0.5
        assert candidates[0].payload == {"company": "TechCorp"}
        assert candidates[1].entity_id == "job-789"
        # Absolute normalization: 0.85 is below expected (0.9355) -> lower score
        assert candidates[1].maxsim_score < candidates[0].maxsim_score

    def test_candidate_is_frozen_dataclass(self) -> None:
        """Test that candidate is a frozen dataclass."""
        assert dataclasses.is_dataclass(NativeMaxSimCandidate)
        params = getattr(NativeMaxSimCandidate, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestNativeMaxSimQueryParams:
    """Tests for NativeMaxSimQueryParams dataclass."""

    def test_default_params(self) -> None:
        """Test default parameter values."""
        params = NativeMaxSimQueryParams()

        assert params.prefetch_limit == 200
        assert params.final_limit == 150
        assert params.filters is None

    def test_custom_params(self) -> None:
        """Test custom parameter values."""
        params = NativeMaxSimQueryParams(
            prefetch_limit=500,
            final_limit=100,
            filters={"is_active": True},
        )

        assert params.prefetch_limit == 500
        assert params.final_limit == 100
        assert params.filters == {"is_active": True}


class TestBuildNativeMaxSimQuery:
    """Tests for build_native_maxsim_query helper function."""

    def test_build_query_with_defaults(self) -> None:
        """Test building query with default params."""
        query = build_native_maxsim_query(
            muvera_fde=[0.1] * 100,
            colbert_tokens=[[0.1] * 48 for _ in range(5)],
            sparse_indices=[1, 2, 3],
            sparse_values=[0.5, 0.3, 0.2],
        )

        assert len(query.muvera_fde) == 100
        assert len(query.colbert_tokens) == 5
        assert query.prefetch_limit == 200
        assert query.final_limit == 150

    def test_build_query_with_custom_params(self) -> None:
        """Test building query with custom params."""
        params = NativeMaxSimQueryParams(
            prefetch_limit=300,
            final_limit=75,
            filters={"status": "active"},
        )

        query = build_native_maxsim_query(
            muvera_fde=[0.1] * 100,
            colbert_tokens=[[0.1] * 48],
            sparse_indices=[],
            sparse_values=[],
            params=params,
        )

        assert query.prefetch_limit == 300
        assert query.final_limit == 75
        assert query.filters == {"status": "active"}


class TestNativeMaxSimStage:
    """Tests for NativeMaxSimStage."""

    @pytest.fixture
    def mock_qdrant_client(self) -> MagicMock:
        """Create mock Qdrant client."""
        return MagicMock()

    @pytest.fixture
    def stage(self, mock_qdrant_client: MagicMock) -> NativeMaxSimStage:
        """Create stage with mock client."""
        return NativeMaxSimStage(
            qdrant_client=mock_qdrant_client,
            collection_name="jobs_active",
            default_prefetch_limit=200,
            default_final_limit=150,
            normalization=DEFAULT_NORM_PARAMS,
        )

    def test_stage_initialization(self, mock_qdrant_client: MagicMock) -> None:
        """Test stage initialization."""
        stage = NativeMaxSimStage(
            qdrant_client=mock_qdrant_client,
            collection_name="test_collection",
            default_prefetch_limit=300,
            default_final_limit=100,
            normalization=DEFAULT_NORM_PARAMS,
        )

        assert stage._collection_name == "test_collection"
        assert stage._default_prefetch_limit == 300
        assert stage._default_final_limit == 100

    def test_stage_requires_normalization(self, mock_qdrant_client: MagicMock) -> None:
        """Test that stage raises ValueError if normalization not provided."""
        with pytest.raises(ValueError, match="normalization must be provided"):
            NativeMaxSimStage(
                qdrant_client=mock_qdrant_client,
                collection_name="test_collection",
            )

    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_with_sparse(
        self,
        stage: NativeMaxSimStage,
    ) -> None:
        """Test retrieval with sparse vectors (hybrid mode)."""
        from nohiki_qdrant_client import MultiStageSearchResult

        mock_results = [
            MultiStageSearchResult(
                id="job-1",
                muvera_score=0.9,
                maxsim_score=15.0,
                payload={"title": "Engineer"},
            ),
            MultiStageSearchResult(
                id="job-2",
                muvera_score=0.8,
                maxsim_score=12.0,
                payload={"title": "Developer"},
            ),
        ]

        with patch(
            "job_correlation_evaluation_service.services.scoring.stages.native_maxsim.search_multistage",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            query = NativeMaxSimQuery(
                muvera_fde=[0.1] * 100,
                colbert_tokens=[[0.1] * 48],
                sparse_indices=[1, 2, 3],
                sparse_values=[0.5, 0.3, 0.2],
                prefetch_limit=200,
                final_limit=50,
            )

            candidates = await stage.retrieve_and_rerank(query)

            assert len(candidates) == 2
            assert candidates[0].entity_id == "job-1"
            # Absolute normalization: high raw scores normalize to high values
            assert candidates[0].maxsim_score > 0.5
            assert candidates[1].entity_id == "job-2"
            # Both high scores normalize to high values; job-1 > job-2
            assert candidates[1].maxsim_score > 0.5
            assert candidates[0].maxsim_score >= candidates[1].maxsim_score

    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_without_sparse(
        self,
        stage: NativeMaxSimStage,
    ) -> None:
        """Test retrieval without sparse vectors (MUVERA-only mode)."""
        from nohiki_qdrant_client import MultiStageSearchResult

        mock_results = [
            MultiStageSearchResult(
                id="job-1",
                muvera_score=0.9,
                maxsim_score=15.0,
                payload={},
            ),
        ]

        with patch(
            "job_correlation_evaluation_service.services.scoring.stages.native_maxsim.search_muvera_then_maxsim",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            query = NativeMaxSimQuery(
                muvera_fde=[0.1] * 100,
                colbert_tokens=[[0.1] * 48],
                sparse_indices=[],  # Empty sparse
                sparse_values=[],
            )

            candidates = await stage.retrieve_and_rerank(query)

            assert len(candidates) == 1
            assert candidates[0].entity_id == "job-1"

    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_empty_results(
        self,
        stage: NativeMaxSimStage,
    ) -> None:
        """Test retrieval with no results."""
        with patch(
            "job_correlation_evaluation_service.services.scoring.stages.native_maxsim.search_multistage",
            new_callable=AsyncMock,
            return_value=[],
        ):
            query = NativeMaxSimQuery(
                muvera_fde=[0.1] * 100,
                colbert_tokens=[[0.1] * 48],
                sparse_indices=[1],
                sparse_values=[0.5],
            )

            candidates = await stage.retrieve_and_rerank(query)

            assert len(candidates) == 0

    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_from_retrieval_candidates(
        self,
        stage: NativeMaxSimStage,
    ) -> None:
        """Test that pre-retrieved candidates are ignored in native mode."""
        from job_correlation_evaluation_service.services.scoring.stages.muvera_retrieval import (
            RetrievalCandidate,
        )
        from nohiki_qdrant_client import MultiStageSearchResult

        mock_results = [
            MultiStageSearchResult(
                id="job-fresh",
                muvera_score=0.95,
                maxsim_score=18.0,
                payload={},
            ),
        ]

        pre_retrieved = [
            RetrievalCandidate(
                entity_id="job-old",
                muvera_score=0.5,
                payload={},
            ),
        ]

        with patch(
            "job_correlation_evaluation_service.services.scoring.stages.native_maxsim.search_multistage",
            new_callable=AsyncMock,
            return_value=mock_results,
        ):
            query = NativeMaxSimQuery(
                muvera_fde=[0.1] * 100,
                colbert_tokens=[[0.1] * 48],
                sparse_indices=[1],
                sparse_values=[0.5],
            )

            candidates = await stage.retrieve_and_rerank_from_retrieval_candidates(query, pre_retrieved)

            # Should return fresh results, not pre-retrieved
            assert len(candidates) == 1
            assert candidates[0].entity_id == "job-fresh"

    @pytest.mark.asyncio
    async def test_retrieve_with_filters(
        self,
        stage: NativeMaxSimStage,
    ) -> None:
        """Test retrieval with payload filters."""
        from nohiki_qdrant_client import MultiStageSearchResult

        mock_results = [
            MultiStageSearchResult(
                id="job-active",
                muvera_score=0.9,
                maxsim_score=15.0,
                payload={"is_active": True},
            ),
        ]

        with patch(
            "job_correlation_evaluation_service.services.scoring.stages.native_maxsim.search_multistage",
            new_callable=AsyncMock,
            return_value=mock_results,
        ) as mock_search:
            query = NativeMaxSimQuery(
                muvera_fde=[0.1] * 100,
                colbert_tokens=[[0.1] * 48],
                sparse_indices=[1],
                sparse_values=[0.5],
                filters={"is_active": True},
            )

            await stage.retrieve_and_rerank(query)

            # Verify search was called
            mock_search.assert_called_once()
            call_args = mock_search.call_args
            multi_query = call_args[0][2]  # Third positional arg is the query
            assert multi_query.filters == {"is_active": True}

"""Unit tests for ScoringPipeline batch operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.pipeline import (
    QueryEncoding,
    ScoringPipeline,
)

if TYPE_CHECKING:
    from nohiki.job.listing.v1 import ListingSnapshot
    from nohiki.user.pref.v1 import SearchPrefSnapshot


class TestQueryEncoding:
    """Tests for QueryEncoding dataclass."""

    def test_creates_with_required_fields(self) -> None:
        """Test creating query encoding with required fields."""
        muvera_fde = [0.1, 0.2, 0.3]
        colbert_tokens = np.array([[0.1, 0.2], [0.3, 0.4]])
        sparse_indices = [1, 5, 10]
        sparse_values = [0.5, 0.3, 0.2]
        text = "python backend developer"

        encoding = QueryEncoding(
            muvera_fde=muvera_fde,
            colbert_tokens=colbert_tokens,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            text=text,
        )

        assert encoding.muvera_fde == muvera_fde
        assert np.array_equal(encoding.colbert_tokens, colbert_tokens)
        assert encoding.sparse_indices == sparse_indices
        assert encoding.sparse_values == sparse_values
        assert encoding.text == text


class TestScoringPipelineScoreListingsByIds:
    """Tests for score_listings_by_ids method."""

    @pytest.fixture
    def mock_native(self) -> AsyncMock:
        """Create mock native MaxSim client."""
        return AsyncMock()

    @pytest.fixture
    def mock_llm_rerank(self) -> AsyncMock:
        """Create mock LLM rerank client."""
        client = AsyncMock()
        client.close = AsyncMock()
        return client

    @pytest.fixture
    def mock_l2r(self) -> MagicMock:
        """Create mock L2R scorer."""
        return MagicMock()

    @pytest.fixture
    def pipeline(self, mock_native: AsyncMock, mock_llm_rerank: AsyncMock, mock_l2r: MagicMock) -> ScoringPipeline:
        """Create pipeline with mocks."""
        pipeline = object.__new__(ScoringPipeline)
        object.__setattr__(pipeline, "_native", mock_native)
        object.__setattr__(pipeline, "_llm_rerank", mock_llm_rerank)
        object.__setattr__(pipeline, "_l2r", mock_l2r)
        return pipeline

    @pytest.fixture
    def mock_profile(self) -> SearchPrefSnapshot:
        """Create mock profile."""
        profile = MagicMock(spec=["id", "search_keywords"])
        profile.id = "profile-123"
        profile.search_keywords = ["python", "backend"]
        return cast("SearchPrefSnapshot", profile)

    @pytest.fixture
    def mock_listings(self) -> dict[str, ListingSnapshot]:
        """Create mock listings dict."""
        job1 = MagicMock(spec=["id", "title"])
        job1.id = "job-1"
        job1.title = "Software Engineer"

        job2 = MagicMock(spec=["id", "title"])
        job2.id = "job-2"
        job2.title = "Backend Developer"

        return {
            "job-1": cast("ListingSnapshot", job1),
            "job-2": cast("ListingSnapshot", job2),
        }

    @pytest.fixture
    def query_encoding(self) -> QueryEncoding:
        """Create query encoding."""
        return QueryEncoding(
            muvera_fde=[0.1, 0.2, 0.3],
            colbert_tokens=np.array([[0.1, 0.2], [0.3, 0.4]]),
            sparse_indices=[1, 5],
            sparse_values=[0.5, 0.3],
            text="python backend developer",
        )

    @pytest.mark.asyncio
    async def test_score_listings_by_ids_empty_listings(
        self,
        pipeline: ScoringPipeline,
        query_encoding: QueryEncoding,
        mock_profile: SearchPrefSnapshot,
    ) -> None:
        """Test returns empty list for empty listings dict."""
        result = await pipeline.score_listings_by_ids(
            query_encoding=query_encoding,
            profile=mock_profile,
            listings={},
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_score_listings_by_ids_no_maxsim_results(
        self,
        pipeline: ScoringPipeline,
        mock_native: AsyncMock,
        query_encoding: QueryEncoding,
        mock_profile: SearchPrefSnapshot,
        mock_listings: dict[str, ListingSnapshot],
    ) -> None:
        """Test returns empty when Qdrant returns no results."""
        mock_native.score_by_entity_ids.return_value = []

        result = await pipeline.score_listings_by_ids(
            query_encoding=query_encoding,
            profile=mock_profile,
            listings=mock_listings,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_score_listings_by_ids_success(
        self,
        pipeline: ScoringPipeline,
        query_encoding: QueryEncoding,
        mock_profile: SearchPrefSnapshot,
        mock_listings: dict[str, ListingSnapshot],
    ) -> None:
        """Test successful batch scoring with embeddings."""
        from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
            NativeMaxSimCandidate,
        )

        mock_maxsim_result = NativeMaxSimCandidate(
            entity_id="job-1",
            maxsim_score=0.85,
            payload={"title": "Engineer"},
        )

        native_mock = cast(AsyncMock, pipeline._native.score_by_entity_ids)
        native_mock.return_value = [mock_maxsim_result]

        mock_scored = MagicMock()
        mock_scored.entity_id = "job-1"
        mock_scored.final_score = 85
        l2r_mock = cast(MagicMock, pipeline._l2r.score_batch)
        l2r_mock.return_value = [mock_scored]

        result = await pipeline.score_listings_by_ids(
            query_encoding=query_encoding,
            profile=mock_profile,
            listings=mock_listings,
        )

        assert len(result) == 1
        assert result[0].entity_id == "job-1"
        native_mock.assert_awaited_once()
        l2r_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_score_listings_by_ids_type_error_logged(
        self,
        pipeline: ScoringPipeline,
        query_encoding: QueryEncoding,
        mock_profile: SearchPrefSnapshot,
        mock_listings: dict[str, ListingSnapshot],
    ) -> None:
        """Test TypeError is re-raised after logging."""
        native_mock = cast(AsyncMock, pipeline._native.score_by_entity_ids)
        native_mock.side_effect = TypeError("Invalid type")

        with pytest.raises(TypeError, match="Invalid type"):
            await pipeline.score_listings_by_ids(
                query_encoding=query_encoding,
                profile=mock_profile,
                listings=mock_listings,
            )


class TestScoringPipelineScoreListingDirect:
    """Tests for score_listing_direct method."""


class TestScoringPipelineClose:
    """Tests for pipeline close method."""

    @pytest.mark.asyncio
    async def test_close_calls_llm_rerank_close(self) -> None:
        """Test close method calls LLM rerank close."""
        mock_llm_rerank = AsyncMock()
        mock_llm_rerank.close = AsyncMock()

        pipeline = object.__new__(ScoringPipeline)
        object.__setattr__(pipeline, "_llm_rerank", mock_llm_rerank)
        object.__setattr__(pipeline, "_native", AsyncMock())
        object.__setattr__(pipeline, "_l2r", MagicMock())

        await pipeline.close()

        mock_llm_rerank.close.assert_awaited_once()

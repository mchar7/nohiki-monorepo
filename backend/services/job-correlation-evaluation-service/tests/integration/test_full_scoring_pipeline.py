"""Integration tests for the Scoring Pipeline.

These tests verify the end-to-end scoring flow using mocked components
that simulate the native Qdrant multi-stage search.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from job_correlation_evaluation_service.core.config import get_manifest
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT
from job_correlation_evaluation_service.services.scoring.pipeline import (
    PipelineResult,
    QueryEncoding,
    ScoringPipeline,
)
from job_correlation_evaluation_service.services.scoring.pipeline_config import (
    MaxSimMode,
    PipelineSettings,
)
from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    DeterministicFinalStage,
    ScoredCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import (
    LLMRerankStage,
    RerankCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
    NativeMaxSimCandidate,
    NativeMaxSimStage,
)
from pytest_unused_fixtures import ignore_unused_fixture


def _make_test_settings(**kwargs: object) -> PipelineSettings:
    """Create PipelineSettings with test defaults."""
    defaults: dict[str, object] = {
        "stage1_candidate_limit": 1000,
        "stage2_candidate_limit": 150,
        "stage2_mode": MaxSimMode.NATIVE,
        "stage2_prefetch_limit": 200,
        "stage3_enabled": False,
        "stage3_candidate_limit": 50,
        "reranker_endpoint_url": "",
        "rerank_timeout_seconds": 30.0,
        "rerank_batch_size": 16,
        "circuit_breaker_failure_threshold": 5,
        "circuit_breaker_recovery_seconds": 30,
        "weight_maxsim": 0.30,
        "weight_title": 0.70,
        "sparse_boost_weight": 0.15,
    }
    defaults |= kwargs
    return PipelineSettings(**cast("dict[str, Any]", defaults))


@pytest.mark.integration
class TestScoringPipelineFlow:
    """Integration tests for the complete scoring pipeline."""

    @pytest.fixture
    @ignore_unused_fixture
    def sample_query_encoding(self) -> QueryEncoding:
        """Create a sample query encoding for testing."""
        manifest = get_manifest()
        return QueryEncoding(
            muvera_fde=[0.1] * manifest.muvera_output_dimension,
            sparse_indices=[1, 5, 10, 20, 50],
            sparse_values=[0.5, 0.4, 0.3, 0.2, 0.1],
            colbert_tokens=np.array(
                [[0.05] * manifest.late_interaction.token_dim for _ in range(32)],
                dtype=np.float32,
            ),
            text="python backend developer with kubernetes experience",
        )

    @pytest.fixture
    @ignore_unused_fixture
    def mock_native_candidates(self) -> list[NativeMaxSimCandidate]:
        """Create mock candidates from native Stage 1+2."""
        return [
            NativeMaxSimCandidate(
                entity_id=f"listing-{i:03d}",
                maxsim_score=15.0 - (i * 0.5),
                payload={
                    "title": f"Software Engineer {i}",
                    "company_name": f"TechCorp {i}",
                },
            )
            for i in range(10)
        ]

    @pytest.fixture
    @ignore_unused_fixture
    def mock_scored_candidates(self) -> list[ScoredCandidate]:
        """Create mock scored candidates from Stage 4."""
        return [
            ScoredCandidate(
                entity_id=f"listing-{i:03d}",
                maxsim_score=15.0 - (i * 0.5),
                rerank_score=0.85 - (i * 0.02),
                rank_index=(90 - (i * 5)) / 100.0,
                final_score=90 - (i * 5),
                feature_vector=tuple([0.5] * FEATURE_COUNT),
                factor_attributions=(),
            )
            for i in range(5)
        ]

    @pytest.mark.asyncio
    async def test_pipeline_without_llm_rerank(
        self,
        sample_query_encoding: QueryEncoding,
        mock_native_candidates: list[NativeMaxSimCandidate],
        mock_scored_candidates: list[ScoredCandidate],
    ) -> None:
        """Test pipeline with LLM reranking disabled."""
        native_stage = MagicMock(spec=NativeMaxSimStage)
        native_stage.retrieve_and_rerank = AsyncMock(return_value=mock_native_candidates)

        llm_stage = MagicMock(spec=LLMRerankStage)
        llm_stage.rerank = AsyncMock()

        l2r_stage = MagicMock(spec=DeterministicFinalStage)
        l2r_stage.score_batch.return_value = mock_scored_candidates

        settings = _make_test_settings(stage3_enabled=False)

        pipeline = ScoringPipeline(
            native_stage=native_stage,
            llm_rerank_stage=llm_stage,
            l2r_stage=l2r_stage,
            settings=settings,
        )

        mock_profile = MagicMock()
        mock_listings = {f"listing-{i:03d}": MagicMock() for i in range(20)}

        result = await pipeline.score(
            query_encoding=sample_query_encoding,
            profile=mock_profile,
            listings=mock_listings,
            use_llm_rerank=False,
        )

        llm_stage.rerank.assert_not_called()
        assert isinstance(result, PipelineResult)
        assert "deterministic_final" in result.stages_completed

    @pytest.mark.asyncio
    async def test_pipeline_empty_retrieval(
        self,
        sample_query_encoding: QueryEncoding,
    ) -> None:
        """Test pipeline handles empty Stage 1+2 results gracefully."""
        native_stage = MagicMock(spec=NativeMaxSimStage)
        native_stage.retrieve_and_rerank = AsyncMock(return_value=[])

        llm_stage = MagicMock(spec=LLMRerankStage)
        l2r_stage = MagicMock(spec=DeterministicFinalStage)

        pipeline = ScoringPipeline(
            native_stage=native_stage,
            llm_rerank_stage=llm_stage,
            l2r_stage=l2r_stage,
            settings=_make_test_settings(),
        )

        mock_profile = MagicMock()

        result = await pipeline.score(
            query_encoding=sample_query_encoding,
            profile=mock_profile,
            listings={},
        )

        assert len(result.candidates) == 0
        assert result.top_candidate is None
        assert result.stage1_2_count == 0

    @pytest.mark.asyncio
    async def test_pipeline_timing_recorded(
        self,
        sample_query_encoding: QueryEncoding,
        mock_native_candidates: list[NativeMaxSimCandidate],
        mock_scored_candidates: list[ScoredCandidate],
    ) -> None:
        """Test that pipeline records timing for each stage."""
        native_stage = MagicMock(spec=NativeMaxSimStage)
        native_stage.retrieve_and_rerank = AsyncMock(return_value=mock_native_candidates)

        llm_stage = MagicMock(spec=LLMRerankStage)
        llm_stage.rerank = AsyncMock(
            return_value=[
                RerankCandidate(
                    entity_id=c.entity_id,
                    maxsim_score=c.maxsim_score,
                    rerank_score=0.0,
                    payload=c.payload,
                )
                for c in mock_native_candidates
            ]
        )

        l2r_stage = MagicMock(spec=DeterministicFinalStage)
        l2r_stage.score_batch.return_value = mock_scored_candidates

        pipeline = ScoringPipeline(
            native_stage=native_stage,
            llm_rerank_stage=llm_stage,
            l2r_stage=l2r_stage,
            settings=_make_test_settings(),
        )

        mock_profile = MagicMock()
        mock_listings = {f"listing-{i:03d}": MagicMock() for i in range(20)}

        result = await pipeline.score(
            query_encoding=sample_query_encoding,
            profile=mock_profile,
            listings=mock_listings,
        )

        assert result.total_latency_ms > 0


@pytest.mark.integration
class TestPipelineResultMethods:
    """Integration tests for PipelineResult helper methods."""

    @pytest.fixture
    @ignore_unused_fixture
    def sample_candidates(self) -> list[ScoredCandidate]:
        """Create sample scored candidates."""
        return [
            ScoredCandidate(
                entity_id=f"job-{i}",
                maxsim_score=15.0 - (i * 0.4),
                rerank_score=0.8 - (i * 0.03),
                rank_index=(85 - (i * 8)) / 100.0,
                final_score=85 - (i * 8),
                feature_vector=tuple([0.5] * FEATURE_COUNT),
                factor_attributions=(),
            )
            for i in range(10)
        ]

    def test_top_n_returns_correct_count(
        self,
        sample_candidates: list[ScoredCandidate],
    ) -> None:
        """Test top_n returns correct number of candidates."""
        result = PipelineResult(
            candidates=sample_candidates,
            stages_completed=["muvera_ann", "colbert_maxsim", "deterministic_final"],
        )

        top3 = result.top_n(3)
        assert len(top3) == 3

        top5 = result.top_n(5)
        assert len(top5) == 5

    def test_top_n_handles_larger_n(
        self,
        sample_candidates: list[ScoredCandidate],
    ) -> None:
        """Test top_n handles n larger than candidate count."""
        result = PipelineResult(candidates=sample_candidates[:3])

        top10 = result.top_n(10)
        assert len(top10) == 3

    def test_candidates_sorted_by_score(
        self,
        sample_candidates: list[ScoredCandidate],
    ) -> None:
        """Test candidates are sorted by final_score descending."""
        result = PipelineResult(candidates=sample_candidates)

        for i in range(len(result.candidates) - 1):
            assert result.candidates[i].final_score >= result.candidates[i + 1].final_score

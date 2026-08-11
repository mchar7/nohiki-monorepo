"""Unit tests for Scoring Pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT
from job_correlation_evaluation_service.services.scoring.pipeline import (
    PipelineResult,
    QueryEncoding,
    ScoringPipeline,
    StageTimings,
)
from job_correlation_evaluation_service.services.scoring.pipeline_config import (
    MaxSimMode,
    PipelineSettings,
)
from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    ScoredCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import (
    RerankCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
    NativeMaxSimCandidate,
    NativeMaxSimStage,
)


class TestStageTimings:
    """Tests for StageTimings dataclass."""

    def test_default_timings(self) -> None:
        """Test default timing values."""
        timings = StageTimings()

        assert timings.stage1_2_ms == pytest.approx(0.0)
        assert timings.stage3_ms == pytest.approx(0.0)
        assert timings.stage4_ms == pytest.approx(0.0)

    def test_total_ms(self) -> None:
        """Test total_ms property."""
        timings = StageTimings(
            stage1_2_ms=50.0,
            stage3_ms=30.0,
            stage4_ms=20.0,
        )

        assert timings.total_ms == pytest.approx(100.0)


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    @pytest.fixture
    def sample_candidates(self) -> list[ScoredCandidate]:
        """Create sample scored candidates."""
        return [
            ScoredCandidate(
                entity_id="job-1",
                maxsim_score=15.0,
                rerank_score=0.8,
                rank_index=0.85,
                final_score=85,
                feature_vector=tuple([0.1] * FEATURE_COUNT),
                factor_attributions=(),
            ),
            ScoredCandidate(
                entity_id="job-2",
                maxsim_score=12.0,
                rerank_score=0.7,
                rank_index=0.70,
                final_score=70,
                feature_vector=tuple([0.1] * FEATURE_COUNT),
                factor_attributions=(),
            ),
        ]

    def test_result_with_candidates(self, sample_candidates: list[ScoredCandidate]) -> None:
        """Test result with candidates."""
        result = PipelineResult(
            candidates=sample_candidates,
            stages_completed=["colbert_maxsim", "deterministic_final"],
            stage1_2_count=100,
            stage3_count=50,
            stage4_count=2,
            total_latency_ms=150.0,
        )

        assert len(result.candidates) == 2
        assert result.stage1_2_count == 100
        assert result.total_latency_ms == pytest.approx(150.0)

    def test_top_candidate(self, sample_candidates: list[ScoredCandidate]) -> None:
        """Test top_candidate property."""
        result = PipelineResult(candidates=sample_candidates)

        assert result.top_candidate is not None
        assert result.top_candidate.entity_id == "job-1"

    def test_top_candidate_empty(self) -> None:
        """Test top_candidate returns None when empty."""
        result = PipelineResult(candidates=[])

        assert result.top_candidate is None

    def test_top_n(self, sample_candidates: list[ScoredCandidate]) -> None:
        """Test top_n method."""
        result = PipelineResult(candidates=sample_candidates)

        top_1 = result.top_n(1)
        assert len(top_1) == 1
        assert top_1[0].entity_id == "job-1"

        top_5 = result.top_n(5)
        assert len(top_5) == 2  # Only 2 candidates available


class TestScoringPipeline:
    """Tests for ScoringPipeline."""

    @pytest.fixture
    def mock_native_stage(self) -> MagicMock:
        """Create mock native MaxSim stage."""
        stage = MagicMock(spec=NativeMaxSimStage)
        stage.retrieve_and_rerank = AsyncMock(
            return_value=[
                NativeMaxSimCandidate(
                    entity_id="job-1",
                    maxsim_score=15.0,
                    payload={"title": "Engineer"},
                ),
                NativeMaxSimCandidate(
                    entity_id="job-2",
                    maxsim_score=12.0,
                    payload={"title": "Developer"},
                ),
            ]
        )
        stage.score_by_entity_ids = AsyncMock(return_value=[])
        return stage

    @pytest.fixture
    def mock_llm_rerank_stage(self) -> AsyncMock:
        """Create mock LLM rerank stage."""
        stage = AsyncMock()
        stage.rerank.return_value = [
            RerankCandidate(
                entity_id="job-1",
                maxsim_score=15.0,
                rerank_score=0.85,
                payload={},
            ),
        ]
        stage.close = AsyncMock()
        return stage

    @pytest.fixture
    def mock_l2r_stage(self) -> MagicMock:
        """Create mock deterministic final stage."""
        stage = MagicMock()
        stage.score_batch.return_value = [
            ScoredCandidate(
                entity_id="job-1",
                maxsim_score=15.0,
                rerank_score=0.85,
                rank_index=0.90,
                final_score=90,
                feature_vector=tuple([0.1] * FEATURE_COUNT),
                factor_attributions=(),
            ),
        ]
        return stage

    @pytest.fixture
    def settings(self) -> PipelineSettings:
        """Create pipeline settings."""
        return PipelineSettings(
            stage1_candidate_limit=1000,
            stage2_candidate_limit=150,
            stage2_mode=MaxSimMode.NATIVE,
            stage2_prefetch_limit=200,
            stage3_enabled=False,
            stage3_candidate_limit=50,
            reranker_endpoint_url="",
            rerank_timeout_seconds=30.0,
            rerank_batch_size=16,
            circuit_breaker_failure_threshold=5,
            circuit_breaker_recovery_seconds=30,
            weight_maxsim=0.30,
            weight_title=0.70,
            sparse_boost_weight=0.15,
        )

    @pytest.fixture
    def pipeline(
        self,
        mock_native_stage: MagicMock,
        mock_llm_rerank_stage: AsyncMock,
        mock_l2r_stage: MagicMock,
        settings: PipelineSettings,
    ) -> ScoringPipeline:
        """Create pipeline with mocked stages."""
        return ScoringPipeline(
            native_stage=mock_native_stage,
            llm_rerank_stage=mock_llm_rerank_stage,
            l2r_stage=mock_l2r_stage,
            settings=settings,
        )

    @pytest.fixture
    def query_encoding(self) -> QueryEncoding:
        """Create sample query encoding."""
        return QueryEncoding(
            muvera_fde=[0.1] * 2048,
            sparse_indices=[1, 5, 10],
            sparse_values=[0.5, 0.3, 0.2],
            colbert_tokens=np.random.default_rng(42).random((10, 48)).astype(np.float32),
            text="software engineer python",
        )

    @pytest.mark.asyncio
    async def test_score_basic(
        self,
        pipeline: ScoringPipeline,
        query_encoding: QueryEncoding,
        mock_native_stage: MagicMock,
        mock_l2r_stage: MagicMock,
    ) -> None:
        """Test basic scoring flow."""
        # Create mock profile and listings
        mock_profile = MagicMock()
        mock_listings = {"job-1": MagicMock(), "job-2": MagicMock()}

        result = await pipeline.score(
            query_encoding=query_encoding,
            profile=mock_profile,
            listings=mock_listings,
        )

        assert len(result.candidates) == 1  # L2R returns 1
        assert result.stage1_2_count == 2  # Native stage returns 2
        assert "colbert_maxsim" in result.stages_completed
        assert "deterministic_final" in result.stages_completed

        # Verify stages were called
        mock_native_stage.retrieve_and_rerank.assert_called_once()
        mock_l2r_stage.score_batch.assert_called_once()

    def test_rejects_stage3_enabled_settings(
        self,
        mock_native_stage: MagicMock,
        mock_llm_rerank_stage: AsyncMock,
        mock_l2r_stage: MagicMock,
    ) -> None:
        """Stage 3 (LLM rerank) cannot be enabled with deterministic final ranking."""
        settings = PipelineSettings(
            stage1_candidate_limit=1000,
            stage2_candidate_limit=150,
            stage2_mode=MaxSimMode.NATIVE,
            stage2_prefetch_limit=200,
            stage3_enabled=True,
            stage3_candidate_limit=50,
            reranker_endpoint_url="",
            rerank_timeout_seconds=30.0,
            rerank_batch_size=16,
            circuit_breaker_failure_threshold=5,
            circuit_breaker_recovery_seconds=30,
            weight_maxsim=0.30,
            weight_title=0.70,
            sparse_boost_weight=0.15,
        )

        with pytest.raises(ValueError, match="Stage 3 must remain disabled"):
            ScoringPipeline(
                native_stage=mock_native_stage,
                llm_rerank_stage=mock_llm_rerank_stage,
                l2r_stage=mock_l2r_stage,
                settings=settings,
            )

    @pytest.mark.asyncio
    async def test_score_override_llm_rerank_rejected(
        self,
        pipeline: ScoringPipeline,
        query_encoding: QueryEncoding,
    ) -> None:
        """Forcing use_llm_rerank at call time is rejected under deterministic final ranking."""
        mock_profile = MagicMock()
        mock_listings = {"job-1": MagicMock()}

        with pytest.raises(ValueError, match="Stage 3 cannot be enabled"):
            await pipeline.score(
                query_encoding=query_encoding,
                profile=mock_profile,
                listings=mock_listings,
                use_llm_rerank=True,
            )

    @pytest.mark.asyncio
    async def test_score_empty_results(
        self,
        mock_native_stage: MagicMock,
        mock_llm_rerank_stage: AsyncMock,
        mock_l2r_stage: MagicMock,
        settings: PipelineSettings,
        query_encoding: QueryEncoding,
    ) -> None:
        """Test scoring with no results from native stage."""
        mock_native_stage.retrieve_and_rerank = AsyncMock(return_value=[])

        pipeline = ScoringPipeline(
            native_stage=mock_native_stage,
            llm_rerank_stage=mock_llm_rerank_stage,
            l2r_stage=mock_l2r_stage,
            settings=settings,
        )

        mock_profile = MagicMock()
        mock_listings = {}

        result = await pipeline.score(
            query_encoding=query_encoding,
            profile=mock_profile,
            listings=mock_listings,
        )

        assert len(result.candidates) == 0
        assert result.stage1_2_count == 0
        # L2R should not be called if no candidates
        mock_l2r_stage.score_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_score_with_filters(
        self,
        pipeline: ScoringPipeline,
        query_encoding: QueryEncoding,
        mock_native_stage: MagicMock,
    ) -> None:
        """Test scoring with payload filters."""
        mock_profile = MagicMock()
        mock_listings = {"job-1": MagicMock()}

        await pipeline.score(
            query_encoding=query_encoding,
            profile=mock_profile,
            listings=mock_listings,
            filters={"is_active": True},
        )

        # Verify filters were passed to native stage
        call_args = mock_native_stage.retrieve_and_rerank.call_args
        query = call_args[0][0]  # First positional arg
        assert query.filters == {"is_active": True}

    @pytest.mark.asyncio
    async def test_close(
        self,
        pipeline: ScoringPipeline,
        mock_llm_rerank_stage: AsyncMock,
    ) -> None:
        """Test pipeline close method."""
        await pipeline.close()

        mock_llm_rerank_stage.close.assert_called_once()

    def test_create_factory(self) -> None:
        """Test create factory method."""
        mock_qdrant = MagicMock()

        with (
            patch("job_correlation_evaluation_service.services.scoring.pipeline.NativeMaxSimStage") as mock_stage_cls,
            patch("job_correlation_evaluation_service.services.scoring.pipeline.LLMRerankStage") as mock_llm_cls,
            patch(
                "job_correlation_evaluation_service.services.scoring.pipeline.DeterministicFinalStage"
            ) as mock_l2r_cls,
        ):
            mock_stage_cls.return_value = MagicMock()
            mock_llm_cls.from_settings.return_value = MagicMock()
            mock_l2r_cls.create.return_value = MagicMock()

            pipeline = ScoringPipeline.create(
                qdrant_client=mock_qdrant,
                collection_name="jobs_active",
            )

            assert pipeline is not None
            mock_stage_cls.assert_called_once()
            mock_llm_cls.from_settings.assert_called_once()
            mock_l2r_cls.create.assert_called_once()

    def test_create_raises_when_manifest_missing(self) -> None:
        """Test create factory raises when manifest is missing (no silent fallback)."""
        mock_qdrant = MagicMock()

        with patch("job_correlation_evaluation_service.services.scoring.pipeline.get_manifest") as mock_manifest:
            mock_manifest.side_effect = FileNotFoundError("Manifest not found")

            with pytest.raises(FileNotFoundError, match="Manifest not found"):
                ScoringPipeline.create(
                    qdrant_client=mock_qdrant,
                    collection_name="jobs_active",
                )


class TestQueryEncoding:
    """Tests for QueryEncoding dataclass."""

    def test_from_encoding_result(self) -> None:
        """Test QueryEncoding factory method."""
        import numpy as np

        muvera = [0.1] * 10
        sparse_indices = [1, 2, 3]
        sparse_values = [0.5, 0.3, 0.2]
        colbert = np.array([[0.1] * 48] * 10)

        encoding = QueryEncoding.from_encoding_result(
            muvera_fde=muvera,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            colbert_tokens=colbert,
            text="software engineer",
        )

        assert encoding.muvera_fde == muvera
        assert encoding.sparse_indices == sparse_indices
        assert encoding.text == "software engineer"


class TestScoringPipelineScoreListingsByIds:
    """Tests for score_listings_by_ids method."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_listings_empty(self) -> None:
        """Test returns empty list when listings dict is empty."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )

        pipeline = ScoringPipeline(
            native_stage=MagicMock(),
            llm_rerank_stage=MagicMock(),
            l2r_stage=MagicMock(),
            settings=MagicMock(stage3_enabled=False),
        )

        mock_encoding = MagicMock()
        mock_profile = MagicMock()

        result = await pipeline.score_listings_by_ids(mock_encoding, mock_profile, {})

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_maxsim_candidates(self) -> None:
        """Test returns empty when no candidates from Qdrant."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )

        mock_native = MagicMock()
        mock_native.score_by_entity_ids = AsyncMock(return_value=[])

        pipeline = ScoringPipeline(
            native_stage=mock_native,
            llm_rerank_stage=MagicMock(),
            l2r_stage=MagicMock(),
            settings=MagicMock(stage3_enabled=False),
        )

        import numpy as np

        encoding = MagicMock()
        encoding.muvera_fde = [0.1] * 10
        encoding.sparse_indices = [1, 2]
        encoding.sparse_values = [0.5, 0.3]
        encoding.colbert_tokens = np.array([[0.1] * 48] * 5)

        mock_profile = MagicMock()
        mock_listing = MagicMock()

        result = await pipeline.score_listings_by_ids(encoding, mock_profile, {"job-1": mock_listing})

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_colbert_tolist_error(self) -> None:
        """Test handles error when colbert_tokens is not numpy array."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )

        pipeline = ScoringPipeline(
            native_stage=MagicMock(),
            llm_rerank_stage=MagicMock(),
            l2r_stage=MagicMock(),
            settings=MagicMock(stage3_enabled=False),
        )

        encoding = MagicMock()
        encoding.colbert_tokens = "not_an_array"  # Will cause AttributeError on tolist()

        mock_profile = MagicMock()
        mock_listing = MagicMock()

        with pytest.raises(AttributeError):
            await pipeline.score_listings_by_ids(encoding, mock_profile, {"job-1": mock_listing})


class TestScoringPipelineScoreWithInlineEmbeddings:
    """Tests for score_with_inline_embeddings method."""

    def test_raises_when_no_colbert_vector(self) -> None:
        """Test raises ValueError when retrieval_embeddings has no ColBERT vector."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )

        pipeline = ScoringPipeline(
            native_stage=MagicMock(),
            llm_rerank_stage=MagicMock(),
            l2r_stage=MagicMock(),
            settings=MagicMock(stage3_enabled=False),
        )

        mock_listing = MagicMock()
        mock_listing.retrieval_embeddings = []

        mock_profile = MagicMock()
        mock_encoding = MagicMock()

        with pytest.raises(ValueError, match="missing required ColBERT multi-vector"):
            pipeline.score_with_inline_embeddings(mock_listing, mock_profile, mock_encoding)

    def test_raises_when_multi_vector_data_missing(self) -> None:
        """Test raises ValueError when ColBERT vector has no multi_vector data."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )
        from nohiki.ml.v1 import EmbeddingType

        pipeline = ScoringPipeline(
            native_stage=MagicMock(),
            llm_rerank_stage=MagicMock(),
            l2r_stage=MagicMock(),
            settings=MagicMock(stage3_enabled=False),
        )

        mock_colbert_vec = MagicMock()
        mock_colbert_vec.embedding_type = EmbeddingType.COLBERT
        mock_colbert_vec.multi_vector = None

        mock_listing = MagicMock()
        mock_listing.retrieval_embeddings = [mock_colbert_vec]

        mock_profile = MagicMock()
        mock_encoding = MagicMock()

        with pytest.raises(ValueError, match="missing required ColBERT multi-vector"):
            pipeline.score_with_inline_embeddings(mock_listing, mock_profile, mock_encoding)

    @pytest.mark.parametrize(
        ("snapshot_version", "embedding_version", "model_id", "first_value"),
        [
            ("stale", None, None, 0.1),
            (None, "stale", None, 0.1),
            (None, None, "stale-model", 0.1),
            (None, None, None, float("nan")),
            (None, None, None, float("inf")),
        ],
        ids=["stale-snapshot", "stale-artifact", "wrong-model", "nan-coordinate", "infinite-coordinate"],
    )
    def test_rejects_stale_or_nonfinite_colbert_geometry(
        self,
        snapshot_version: str | None,
        embedding_version: str | None,
        model_id: str | None,
        first_value: float,
    ) -> None:
        """Inline scoring rejects untrusted ColBERT artifacts before ranking."""
        from job_correlation_evaluation_service.core.config import get_manifest
        from nohiki.ml.v1 import EmbeddingType, EmbeddingVector, EntityType, MultiVectorData

        manifest = get_manifest()
        collection = manifest.get_collection_config(EntityType.JOB)
        token_dim = manifest.late_interaction.token_dim
        values = [0.1] * token_dim
        values[0] = first_value
        vector = EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=values, num_tokens=1, token_dim=token_dim),
            collection_version=embedding_version or collection.version,
            model_id=model_id or manifest.late_interaction.model_id,
        )
        listing = MagicMock()
        listing.collection_version = snapshot_version or collection.version
        listing.retrieval_embeddings = [vector]
        native = MagicMock()
        native.normalization.per_token_mean = 0.0
        native.normalization.per_token_std = 1.0
        pipeline = ScoringPipeline(
            native_stage=native,
            llm_rerank_stage=MagicMock(),
            l2r_stage=MagicMock(),
            settings=MagicMock(stage3_enabled=False),
        )
        query = QueryEncoding(
            muvera_fde=[0.1],
            colbert_tokens=np.ones((1, token_dim), dtype=np.float32),
            sparse_indices=[],
            sparse_values=[],
            text="query",
        )

        with pytest.raises(ValueError, match=r"stale or malformed|snapshot collection version is stale"):
            pipeline.score_with_inline_embeddings(listing, MagicMock(), query)


class TestScoringPipelineExtractQueryEncodingFromSnapshot:
    """Tests for extract_query_encoding_from_snapshot static method."""

    def test_returns_none_when_no_retrieval_embeddings(self) -> None:
        """Test returns None when query_retrieval_embeddings is empty."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )

        mock_profile = MagicMock()
        mock_profile.query_retrieval_embeddings = []

        result = ScoringPipeline.extract_query_encoding_from_snapshot(mock_profile)
        assert result is None

    def test_returns_none_when_muvera_missing(self) -> None:
        """Test returns None when retrieval embeddings lack MUVERA vector."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )
        from nohiki.ml.v1 import EmbeddingType

        mock_colbert_vec = MagicMock()
        mock_colbert_vec.embedding_type = EmbeddingType.COLBERT

        mock_profile = MagicMock()
        mock_profile.query_retrieval_embeddings = [mock_colbert_vec]

        result = ScoringPipeline.extract_query_encoding_from_snapshot(mock_profile)
        assert result is None

    def test_returns_none_when_colbert_missing(self) -> None:
        """Test returns None when retrieval embeddings lack ColBERT vector."""
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            ScoringPipeline,
        )
        from nohiki.ml.v1 import EmbeddingType

        mock_muvera_vec = MagicMock()
        mock_muvera_vec.embedding_type = EmbeddingType.MUVERA
        mock_muvera_vec.dense = MagicMock()
        mock_muvera_vec.dense.values = [0.1] * 10

        mock_profile = MagicMock()
        mock_profile.query_retrieval_embeddings = [mock_muvera_vec]

        result = ScoringPipeline.extract_query_encoding_from_snapshot(mock_profile)
        assert result is None

    def test_extracts_current_query_encoding(self) -> None:
        """Complete current query artifacts are extracted for scoring."""
        from job_correlation_evaluation_service.core.config import get_manifest
        from job_correlation_evaluation_service.services.scoring.pipeline import (
            QueryEncoding,
            ScoringPipeline,
        )
        from nohiki.ml.v1 import (
            DenseData,
            EmbeddingType,
            EmbeddingVector,
            EntityType,
            MultiVectorData,
            SparseData,
        )
        from nohiki.user.pref.v1 import SearchPrefSnapshot

        manifest = get_manifest()
        collection = manifest.get_collection_config(EntityType.PROFILE)
        dense_name = collection.qdrant.primary_dense_name
        dense_size = collection.qdrant.vectors[dense_name].size
        token_dim = manifest.late_interaction.token_dim
        profile = SearchPrefSnapshot(
            search_keywords=["Data Analyst"],
            query_retrieval_embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.MUVERA,
                    dense=DenseData(values=[0.1] * dense_size),
                    collection_version=collection.version,
                    content_hash="a" * 64,
                ),
                EmbeddingVector(
                    embedding_type=EmbeddingType.COLBERT,
                    multi_vector=MultiVectorData(
                        values=[0.2] * token_dim,
                        num_tokens=1,
                        token_dim=token_dim,
                    ),
                    model_id=manifest.late_interaction.model_id,
                    collection_version=collection.version,
                    content_hash="a" * 64,
                ),
                EmbeddingVector(
                    embedding_type=EmbeddingType.SPARSE,
                    sparse=SparseData(indices=[1, 2, 3], values=[0.5, 0.3, 0.2]),
                    model_id=manifest.sparse.model_id,
                    collection_version=collection.version,
                    content_hash="a" * 64,
                ),
            ],
        )

        result = ScoringPipeline.extract_query_encoding_from_snapshot(profile)

        assert isinstance(result, QueryEncoding)
        assert result.muvera_fde == [0.1] * dense_size
        assert result.sparse_indices == [1, 2, 3]
        assert result.sparse_values == [0.5, 0.3, 0.2]
        assert result.text == "Data Analyst"
        assert result.colbert_tokens.shape == (1, token_dim)

    def test_returns_none_without_sparse_vector(self) -> None:
        """A profile query is unusable unless all three retrieval artifacts are present."""
        from job_correlation_evaluation_service.services.scoring.pipeline import ScoringPipeline
        from nohiki.ml.v1 import EmbeddingType

        mock_muvera_vec = MagicMock()
        mock_muvera_vec.embedding_type = EmbeddingType.MUVERA
        mock_muvera_vec.dense = MagicMock(values=[0.1] * 10)
        mock_colbert_vec = MagicMock()
        mock_colbert_vec.embedding_type = EmbeddingType.COLBERT
        mock_colbert_vec.multi_vector = MagicMock(values=[0.2] * 96, num_tokens=2, token_dim=48)
        mock_profile = MagicMock()
        mock_profile.query_retrieval_embeddings = [mock_muvera_vec, mock_colbert_vec]

        assert ScoringPipeline.extract_query_encoding_from_snapshot(mock_profile) is None

"""4-Stage Scoring Pipeline with Qdrant Native Multi-Stage MaxSim."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, EntityType, MultiVectorData
from nohiki_observability import get_logger

from job_correlation_evaluation_service.core.config import get_manifest
from job_correlation_evaluation_service.services.scoring.constants import (
    PipelineStage,
)
from job_correlation_evaluation_service.services.scoring.pipeline_config import (
    PipelineSettings,
    get_pipeline_settings,
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
    MaxSimNormalizationParams,
    NativeMaxSimQuery,
    NativeMaxSimStage,
    normalize_maxsim_score_absolute,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nohiki.job.listing.v1 import ListingSnapshot
    from nohiki.user.pref.v1 import SearchPrefSnapshot
    from qdrant_client import AsyncQdrantClient

logger = get_logger(__name__)


def _all_finite(values: list[float]) -> bool:
    """Return whether an embedding contains only finite numeric values."""
    return bool(values) and bool(np.isfinite(np.asarray(values, dtype=np.float64)).all())


def _has_current_embedding_version(embedding: EmbeddingVector, expected_version: str) -> bool:
    """Return whether an embedding matches the active artifact version."""
    return embedding.collection_version == expected_version


def _required_query_embeddings(
    profile: SearchPrefSnapshot,
) -> tuple[EmbeddingVector, EmbeddingVector, EmbeddingVector, DenseData, MultiVectorData] | None:
    """Return complete MUVERA, sparse, and ColBERT query artifacts."""
    retrieval = profile.query_retrieval_embeddings
    expected_types = {EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT}
    if (
        not retrieval
        or len(retrieval) != len(expected_types)
        or {emb.embedding_type for emb in retrieval} != expected_types
    ):
        logger.warning(
            "Skipping profile query with incomplete retrieval embeddings",
            reason="required_artifacts_missing_or_duplicated",
        )
        return None

    by_type = {emb.embedding_type: emb for emb in retrieval}
    muvera_vec = by_type[EmbeddingType.MUVERA]
    sparse_vec = by_type[EmbeddingType.SPARSE]
    colbert_vec = by_type[EmbeddingType.COLBERT]
    dense = muvera_vec.dense
    sparse = sparse_vec.sparse
    multi_vector = colbert_vec.multi_vector
    if (
        dense is None
        or not dense.values
        or sparse is None
        or not sparse.indices
        or not sparse.values
        or multi_vector is None
        or not multi_vector.values
    ):
        logger.warning("Skipping profile query with empty retrieval embedding artifact", reason="empty_artifact")
        return None

    metadata = [(embedding.collection_version, embedding.content_hash) for embedding in retrieval]
    if any(not version or not content_hash for version, content_hash in metadata):
        logger.warning("Skipping profile query with incomplete artifact metadata", reason="metadata_missing")
        return None
    if len(set(metadata)) != 1:
        logger.warning("Skipping profile query with mismatched artifact metadata", reason="metadata_mismatch")
        return None

    return muvera_vec, sparse_vec, colbert_vec, dense, multi_vector


def _sparse_query_components(
    sparse_vec: EmbeddingVector | None,
    expected_version: str,
    expected_model_id: str,
) -> tuple[list[int], list[float]] | None:
    """Validate an optional sparse artifact and return its components."""
    indices = sparse_vec.sparse.indices if sparse_vec and sparse_vec.sparse else []
    values = sparse_vec.sparse.values if sparse_vec and sparse_vec.sparse else []
    malformed = (
        len(indices) != len(values)
        or len(set(indices)) != len(indices)
        or any(index < 0 for index in indices)
        or (values and not _all_finite(values))
    )
    stale = bool(
        sparse_vec
        and (
            not _has_current_embedding_version(sparse_vec, expected_version) or sparse_vec.model_id != expected_model_id
        )
    )
    return None if malformed or stale else (indices, values)


@dataclass(frozen=True, slots=True)
class QueryEncoding:
    """Encoded query for pipeline."""

    muvera_fde: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    colbert_tokens: np.ndarray
    text: str

    @classmethod
    def from_encoding_result(
        cls,
        muvera_fde: list[float],
        sparse_indices: list[int],
        sparse_values: list[float],
        colbert_tokens: np.ndarray,
        text: str,
    ) -> QueryEncoding:
        """Create from encoding result components."""
        return cls(
            muvera_fde=muvera_fde,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            colbert_tokens=colbert_tokens,
            text=text,
        )


@dataclass(slots=True)
class PipelineResult:
    """Result from native scoring pipeline."""

    candidates: list[ScoredCandidate]
    stages_completed: list[str] = field(default_factory=list)
    stage1_2_count: int = 0
    stage3_count: int = 0
    stage4_count: int = 0
    total_latency_ms: float = 0.0
    scored_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def top_candidate(self) -> ScoredCandidate | None:
        """Return top-ranked candidate or None if empty."""
        return self.candidates[0] if self.candidates else None

    def top_n(self, n: int) -> list[ScoredCandidate]:
        """Return top N candidates."""
        return self.candidates[:n]


@dataclass(slots=True)
class StageTimings:
    """Timing breakdown for native pipeline stages."""

    stage1_2_ms: float = 0.0
    stage3_ms: float = 0.0
    stage4_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        """Total time across all stages."""
        return self.stage1_2_ms + self.stage3_ms + self.stage4_ms


class ScoringPipeline:
    """4-Stage Scoring Pipeline with Qdrant Native Multi-Stage MaxSim.

    Combines Stage 1 (MUVERA retrieval) and Stage 2 (MaxSim rerank) into a
    single Qdrant multi-stage query, using Qdrant's native multi-vector
    MaxSim support.

    Pipeline Flow:
        Stage 1+2: Native Multi-Stage (Qdrant) → ~150 candidates
        Stage 3: LLM Rerank (optional)         → ~50 candidates
        Stage 4: L2R Final Ranking             → Final ranked list

    Benefits:
        - No S3/Redis round-trips for token retrieval
        - SIMD-optimized MaxSim in Qdrant's Rust core
        - Single network call for retrieval + reranking

    Requirements:
        - Collection must have ColBERT multi-vectors indexed
        - Use create_multivector_collection() for collection setup

    """

    def __init__(
        self,
        native_stage: NativeMaxSimStage,
        llm_rerank_stage: LLMRerankStage,
        l2r_stage: DeterministicFinalStage,
        settings: PipelineSettings,
    ) -> None:
        """Initialize scoring pipeline.

        Args:
            native_stage: Combined Stage 1+2 native MaxSim
            llm_rerank_stage: Stage 3 LLM reranking
            l2r_stage: Stage 4 L2R scoring
            settings: Pipeline configuration

        """
        if settings.stage3_enabled:
            message = "Stage 3 must remain disabled with deterministic final ranking"
            raise ValueError(message)
        self._native = native_stage
        self._llm_rerank = llm_rerank_stage
        self._l2r = l2r_stage
        self._settings = settings

        logger.info(
            "Scoring pipeline initialized",
            stage2_limit=settings.stage2_candidate_limit,
            stage3_enabled=settings.stage3_enabled,
            stage3_limit=settings.stage3_candidate_limit,
        )

    @classmethod
    def create(
        cls,
        qdrant_client: AsyncQdrantClient,
        collection_name: str,
        settings: PipelineSettings | None = None,
    ) -> ScoringPipeline:
        """Create ScoringPipeline with all dependencies.

        Args:
            qdrant_client: Raw Qdrant client for multi-stage search
            collection_name: Collection or alias with ColBERT multi-vectors
            settings: Optional pipeline settings

        Returns:
            Configured ScoringPipeline instance

        """
        settings = settings or get_pipeline_settings()

        manifest = get_manifest()
        norm_params = MaxSimNormalizationParams(
            per_token_mean=manifest.late_interaction.normalization.per_token_sim_mean,
            per_token_std=manifest.late_interaction.normalization.per_token_sim_std,
        )

        native_stage = NativeMaxSimStage(
            qdrant_client=qdrant_client,
            collection_name=collection_name,
            default_prefetch_limit=settings.stage2_prefetch_limit,
            default_final_limit=settings.stage2_candidate_limit,
            normalization=norm_params,
        )

        llm_rerank_stage = LLMRerankStage.from_settings(settings)
        l2r_stage = DeterministicFinalStage.create()

        return cls(
            native_stage=native_stage,
            llm_rerank_stage=llm_rerank_stage,
            l2r_stage=l2r_stage,
            settings=settings,
        )

    async def score(
        self,
        query_encoding: QueryEncoding,
        profile: SearchPrefSnapshot,
        listings: Mapping[str, ListingSnapshot],
        filters: dict[str, Any] | None = None,
        *,
        use_llm_rerank: bool | None = None,
    ) -> PipelineResult:
        """Execute native scoring pipeline.

        Args:
            query_encoding: Encoded query with ColBERT tokens
            profile: User search preferences for feature extraction
            listings: Dict mapping entity_id to ListingSnapshot
            filters: Optional Qdrant payload filters
            use_llm_rerank: Override Stage 3 (default from settings)

        Returns:
            PipelineResult with ranked candidates and metadata

        """
        start_time = time.perf_counter()
        timings = StageTimings()
        stages_completed: list[str] = []

        # Stage 1+2: Native MUVERA + MaxSim (combined)
        stage1_2_start = time.perf_counter()
        native_query = NativeMaxSimQuery(
            muvera_fde=query_encoding.muvera_fde,
            colbert_tokens=query_encoding.colbert_tokens.tolist(),
            sparse_indices=query_encoding.sparse_indices,
            sparse_values=query_encoding.sparse_values,
            filters=filters,
            prefetch_limit=self._settings.stage2_prefetch_limit,
            final_limit=self._settings.stage2_candidate_limit,
        )
        stage1_2_candidates = await self._native.retrieve_and_rerank(native_query)
        timings.stage1_2_ms = (time.perf_counter() - stage1_2_start) * 1000
        stages_completed.append(PipelineStage.COLBERT_MAXSIM)

        if not stage1_2_candidates:
            return PipelineResult(
                candidates=[],
                stages_completed=stages_completed,
                stage1_2_count=0,
                total_latency_ms=timings.total_ms,
            )

        # Stage 3 is intentionally disabled: an external reranker would make
        # the approved deterministic candidate ordering irreproducible.
        if use_llm_rerank:
            message = "Stage 3 cannot be enabled with deterministic final ranking"
            raise ValueError(message)
        stage3_start = time.perf_counter()
        stage3_candidates = [
            RerankCandidate(
                entity_id=c.entity_id,
                maxsim_score=c.maxsim_score,
                rerank_score=0.0,
                payload=c.payload,
            )
            for c in stage1_2_candidates
        ]
        timings.stage3_ms = (time.perf_counter() - stage3_start) * 1000

        # Stage 4: deterministic final ranking
        stage4_start = time.perf_counter()
        stage4_candidates = self._l2r.score_batch(
            candidates=stage3_candidates,
            listings=listings,
            profile=profile,
        )
        timings.stage4_ms = (time.perf_counter() - stage4_start) * 1000
        stages_completed.append(PipelineStage.DETERMINISTIC_FINAL)

        total_latency_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "Scoring pipeline completed",
            stage1_2_count=len(stage1_2_candidates),
            stage3_count=len(stage3_candidates),
            stage4_count=len(stage4_candidates),
            total_latency_ms=total_latency_ms,
            stage_timings={
                "stage1_2_ms": timings.stage1_2_ms,
                "stage3_ms": timings.stage3_ms,
                "stage4_ms": timings.stage4_ms,
            },
        )

        return PipelineResult(
            candidates=stage4_candidates,
            stages_completed=stages_completed,
            stage1_2_count=len(stage1_2_candidates),
            stage3_count=len(stage3_candidates),
            stage4_count=len(stage4_candidates),
            total_latency_ms=total_latency_ms,
        )

    async def score_listings_by_ids(
        self,
        query_encoding: QueryEncoding,
        profile: SearchPrefSnapshot,
        listings: Mapping[str, ListingSnapshot],
    ) -> list[ScoredCandidate]:
        """Score specific listings by ID with REAL embedding similarity.

        Used for backfill: queries Qdrant to compute real MUVERA/MaxSim scores
        for the specified listings, then runs full L2R scoring with those
        real similarity signals.

        Args:
            query_encoding: Profile's query encoding (MUVERA, ColBERT, sparse)
            profile: User search preferences for L2R feature extraction
            listings: Dict mapping entity_id to ListingSnapshot

        Returns:
            List of ScoredCandidates with real embedding similarity scores

        """
        if not listings:
            return []

        entity_ids = list(listings.keys())

        # Build native query from encoding
        try:
            colbert_list = query_encoding.colbert_tokens.tolist()
        except AttributeError:
            logger.exception(
                "colbert_tokens is not a numpy array",
                type=type(query_encoding.colbert_tokens).__name__,
            )
            raise

        native_query = NativeMaxSimQuery(
            muvera_fde=query_encoding.muvera_fde,
            colbert_tokens=colbert_list,
            sparse_indices=query_encoding.sparse_indices,
            sparse_values=query_encoding.sparse_values,
        )

        # Query Qdrant for REAL embedding similarity scores
        try:
            maxsim_candidates = await self._native.score_by_entity_ids(
                query=native_query,
                entity_ids=entity_ids,
            )
        except TypeError as e:
            logger.exception(
                "TypeError in score_by_entity_ids",
                entity_ids=entity_ids,
                query_type=type(native_query).__name__,
                colbert_shape=f"{len(colbert_list)}x{len(colbert_list[0]) if colbert_list else 0}",
                error=str(e),
            )
            raise

        if not maxsim_candidates:
            logger.warning(
                "No MaxSim scores returned from Qdrant for backfill listings",
                num_requested=len(entity_ids),
            )
            return []

        # Convert to RerankCandidates for L2R stage
        rerank_candidates = [
            RerankCandidate(
                entity_id=c.entity_id,
                maxsim_score=c.maxsim_score,
                rerank_score=0.0,  # No LLM rerank for backfill
                payload=c.payload,
            )
            for c in maxsim_candidates
        ]

        # Run L2R scoring with real similarity scores
        scored = self._l2r.score_batch(
            candidates=rerank_candidates,
            listings=listings,
            profile=profile,
        )

        logger.info(
            "Backfill scoring completed with real embeddings",
            requested=len(entity_ids),
            scored=len(scored),
        )

        return scored

    def score_with_inline_embeddings(
        self,
        listing: ListingSnapshot,
        profile: SearchPrefSnapshot,
        query_encoding: QueryEncoding,
    ) -> ScoredCandidate:
        """Score a listing using inline retrieval embeddings and profile query encoding.

        Computes MaxSim locally from the listing's inline ColBERT tokens
        and the profile's query encoding, then runs L2R scoring.

        Args:
            listing: Listing with retrieval_embeddings containing ColBERT multi-vector
            profile: User search preferences
            query_encoding: Profile's query encoding from Qdrant

        Returns:
            ScoredCandidate with real MaxSim score

        Raises:
            ValueError: If ColBERT multi-vector missing from retrieval_embeddings

        """
        colbert_vec = next(
            (emb for emb in listing.retrieval_embeddings if emb.embedding_type == EmbeddingType.COLBERT),
            None,
        )
        if colbert_vec is None or colbert_vec.multi_vector is None:
            msg = "Listing missing required ColBERT multi-vector in retrieval_embeddings"
            raise ValueError(msg)

        manifest = get_manifest()
        expected_version = manifest.get_collection_config(EntityType.JOB).version
        if listing.collection_version != expected_version:
            msg = "Listing snapshot collection version is stale"
            raise ValueError(msg)
        mv = colbert_vec.multi_vector
        if (
            not _has_current_embedding_version(colbert_vec, expected_version)
            or colbert_vec.model_id != manifest.late_interaction.model_id
            or mv.token_dim != manifest.late_interaction.token_dim
            or mv.num_tokens <= 0
            or len(mv.values) != mv.num_tokens * mv.token_dim
            or not _all_finite(mv.values)
        ):
            msg = "Listing ColBERT embedding is stale or malformed"
            raise ValueError(msg)

        maxsim_score = self._compute_maxsim(
            query_tokens=query_encoding.colbert_tokens,
            doc_tokens=mv,
        )

        return self._l2r.score_with_inline_maxsim(
            listing=listing,
            profile=profile,
            maxsim_score=maxsim_score,
        )

    def _compute_maxsim(
        self,
        query_tokens: np.ndarray,
        doc_tokens: MultiVectorData,
    ) -> float:
        """Compute MaxSim score between query and document ColBERT tokens.

        MaxSim = sum over query tokens of max cosine similarity to any doc token.
        Normalized using manifest parameters for absolute comparability.
        """
        doc_array = np.array(doc_tokens.values, dtype=np.float32).reshape(doc_tokens.num_tokens, doc_tokens.token_dim)
        query_norm = query_tokens / (np.linalg.norm(query_tokens, axis=1, keepdims=True) + 1e-9)
        doc_norm = doc_array / (np.linalg.norm(doc_array, axis=1, keepdims=True) + 1e-9)
        sim_matrix = query_norm @ doc_norm.T
        raw_maxsim = float(sim_matrix.max(axis=1).sum())
        norm_params = self._native.normalization
        return normalize_maxsim_score_absolute(
            raw_maxsim=raw_maxsim,
            num_tokens=len(query_tokens),
            per_token_mean=norm_params.per_token_mean,
            per_token_std=norm_params.per_token_std,
        )

    @staticmethod
    def extract_query_encoding_from_snapshot(
        profile: SearchPrefSnapshot,
    ) -> QueryEncoding | None:
        """Extract a query encoding only from complete, current artifacts."""
        required = _required_query_embeddings(profile)
        if required is None:
            return None
        muvera_vec, sparse_vec, colbert_vec, dense, mv = required

        manifest = get_manifest()
        collection_config = manifest.get_collection_config(EntityType.PROFILE)
        expected_version = collection_config.version
        dense_name = collection_config.qdrant.primary_dense_name
        if len(dense.values) != collection_config.qdrant.vectors[dense_name].size:
            logger.warning("Skipping profile query with malformed MUVERA artifact", reason="dimension_mismatch")
            return None
        invalid_geometry = (
            not _has_current_embedding_version(muvera_vec, expected_version)
            or not _has_current_embedding_version(colbert_vec, expected_version)
            or not _has_current_embedding_version(sparse_vec, expected_version)
            or colbert_vec.model_id != manifest.late_interaction.model_id
            or sparse_vec.model_id != manifest.sparse.model_id
            or mv.token_dim != manifest.late_interaction.token_dim
            or mv.num_tokens <= 0
            or len(mv.values) != mv.num_tokens * mv.token_dim
            or not _all_finite(dense.values)
            or not _all_finite(mv.values)
        )
        if invalid_geometry:
            logger.warning("Skipping profile query with stale or malformed artifact", reason="artifact_validation")
            return None
        sparse_components = _sparse_query_components(sparse_vec, expected_version, manifest.sparse.model_id)
        if sparse_components is None:
            logger.warning("Skipping profile query with malformed sparse artifact", reason="sparse_validation")
            return None

        sparse_indices, sparse_values = sparse_components
        query_text = " ".join(profile.search_keywords)
        return QueryEncoding(
            muvera_fde=dense.values,
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            colbert_tokens=np.asarray(mv.values, dtype=np.float32).reshape(mv.num_tokens, mv.token_dim),
            text=query_text,
        )

    async def close(self) -> None:
        """Close pipeline resources."""
        await self._llm_rerank.close()

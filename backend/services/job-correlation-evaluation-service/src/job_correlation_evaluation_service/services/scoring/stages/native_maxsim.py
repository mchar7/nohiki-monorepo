"""Stage 2: Native MaxSim Rerank via Qdrant Multi-Stage Search.

ColBERT MaxSim reranking using Qdrant's native multi-vector
support instead of external S3/Redis token fetching.

MUVERA is used for Stage 1 retrieval (ANN) only, not for scoring features.
MaxSim provides the semantic similarity signal for L2R scoring.

Benefits over external MaxSim computation:
- Eliminates S3/Redis round-trips for token retrieval
- Qdrant's MaxSim is SIMD-optimized in Rust
- Single network call for entire search pipeline (Stage 1 + 2 combined)

Usage:
    stage = NativeMaxSimStage(qdrant_client, collection_name, default_limit=150)
    results = stage.retrieve_and_rerank(query)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nohiki_observability import get_logger
from nohiki_qdrant_client import (
    MultiStageQuery,
    MultiStageSearchResult,
    MuveraMaxSimQuery,
)
from nohiki_qdrant_client.multivector import (
    search_multistage,
    search_muvera_then_maxsim,
)

from job_correlation_evaluation_service.services.scoring.stages.muvera_retrieval import (
    RetrievalCandidate,
)

DEFAULT_STAGE2_LIMIT = 150
MIN_EXPECTED_STD = 0.001


@dataclass(frozen=True, slots=True)
class MaxSimNormalizationParams:
    """Model-intrinsic normalization parameters for MaxSim scores.

    Must be provided explicitly from the manifest: no fallback defaults.
    """

    per_token_mean: float
    per_token_std: float


if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

logger = get_logger(__name__)


def normalize_maxsim_score_absolute(
    raw_maxsim: float,
    num_tokens: int,
    per_token_mean: float,
    per_token_std: float,
) -> float:
    """Normalize a single MaxSim score using model-intrinsic constants.

    Uses absolute normalization based on per-token statistics from the manifest.
    This ensures scores are comparable across batches - a score of 0.8 means
    the same quality regardless of what other results are in the batch.

    Formula:
        1. Compute expected baseline: num_tokens * per_token_mean
        2. Compute expected std: sqrt(num_tokens) * per_token_std (CLT)
        3. Z-score: (raw - baseline) / std
        4. Map z-score to 0-1 range using sigmoid-like transformation

    Args:
        raw_maxsim: Raw MaxSim score from Qdrant (sum of per-token max cosines)
        num_tokens: Number of query tokens
        per_token_mean: Model-intrinsic mean per-token similarity
        per_token_std: Model-intrinsic std per-token similarity

    Returns:
        Normalized score in 0-1 range (absolute, not relative to batch)

    """
    if num_tokens <= 0:
        return 0.5

    # Expected baseline and variance under null hypothesis
    expected = num_tokens * per_token_mean
    expected_std = (num_tokens**0.5) * per_token_std

    if expected_std < MIN_EXPECTED_STD:
        return 0.5

    # Z-score: how many std above/below expected
    z_score = (raw_maxsim - expected) / expected_std

    # Map z-score to 0-1 using tanh (softer than sigmoid, centered at 0.5)
    # z=0 -> 0.5, z=2 -> ~0.96, z=-2 -> ~0.04
    normalized = 0.5 + 0.5 * (z_score / (1.0 + abs(z_score) * 0.5))

    return max(0.0, min(1.0, normalized))


def normalize_maxsim_scores(
    candidates: list[MultiStageSearchResult],
    num_tokens: int,
    per_token_mean: float,
    per_token_std: float,
) -> list[float]:
    """Normalize MaxSim scores using model-intrinsic constants (absolute normalization).

    Unlike per-batch min-max scaling, this uses absolute normalization based on
    the model's expected per-token similarity distribution. This ensures:
    - A batch of poor matches will have LOW normalized scores
    - A batch of excellent matches will have HIGH normalized scores
    - Scores are comparable across different batches

    Args:
        candidates: Raw search results from Qdrant
        num_tokens: Number of query tokens
        per_token_mean: Model-intrinsic mean per-token similarity (from manifest)
        per_token_std: Model-intrinsic std per-token similarity (from manifest)

    Returns:
        List of normalized MaxSim scores (0-1 range, absolute)

    """
    if not candidates:
        return []

    return [
        normalize_maxsim_score_absolute(
            raw_maxsim=c.maxsim_score,
            num_tokens=num_tokens,
            per_token_mean=per_token_mean,
            per_token_std=per_token_std,
        )
        for c in candidates
    ]


@dataclass(frozen=True, slots=True)
class NativeMaxSimQuery:
    """Query parameters for native MaxSim retrieval + reranking."""

    muvera_fde: list[float]
    colbert_tokens: list[list[float]]
    sparse_indices: list[int]
    sparse_values: list[float]
    filters: dict[str, Any] | None = None
    prefetch_limit: int = 200
    final_limit: int = 50

    @property
    def num_tokens(self) -> int:
        """Number of ColBERT tokens in the query."""
        return len(self.colbert_tokens)


@dataclass(frozen=True, slots=True)
class NativeMaxSimCandidate:
    """Candidate from native Qdrant MaxSim reranking with normalized scores."""

    entity_id: str
    maxsim_score: float
    payload: dict[str, Any]

    @classmethod
    def from_results_batch(
        cls,
        results: list[MultiStageSearchResult],
        num_tokens: int,
        per_token_mean: float,
        per_token_std: float,
    ) -> list[NativeMaxSimCandidate]:
        """Create candidates from batch of results with absolute normalization.

        Uses model-intrinsic constants for normalization so scores are
        comparable across batches (not relative to batch contents).

        Args:
            results: Raw search results from Qdrant
            num_tokens: Number of query tokens
            per_token_mean: Model-intrinsic mean (from manifest)
            per_token_std: Model-intrinsic std (from manifest)

        """
        if not results:
            return []

        normalized_scores = normalize_maxsim_scores(results, num_tokens, per_token_mean, per_token_std)

        return [
            cls(
                entity_id=result.id,
                maxsim_score=norm_maxsim,
                payload=result.payload,
            )
            for result, norm_maxsim in zip(results, normalized_scores, strict=True)
        ]

    @property
    def has_maxsim(self) -> bool:
        """Check if MaxSim was successfully computed."""
        return self.maxsim_score > 0.0


class NativeMaxSimStage:
    """Stage 1+2 Combined: Native Qdrant multi-stage search with MaxSim.

    This stage combines MUVERA retrieval and ColBERT MaxSim reranking into
    a single Qdrant query, using Qdrant's native multi-vector support.

    Pipeline Position:
        Stage 1+2: Native Multi-Stage (Qdrant) → ~150 candidates   ← THIS STAGE
        Stage 3: LLM Rerank (optional)         → ~50 candidates
        Stage 4: L2R Final Ranking             → Final ranked list

    Requirements:
        - Collection must have ColBERT multi-vectors indexed
        - Use MultiVectorCollectionConfig for collection setup

    Benefits:
        - No S3/Redis round-trips for token retrieval
        - SIMD-optimized MaxSim in Qdrant's Rust core
        - Single network call for retrieval + reranking
    """

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient,
        collection_name: str,
        default_prefetch_limit: int = 200,
        default_final_limit: int = DEFAULT_STAGE2_LIMIT,
        normalization: MaxSimNormalizationParams | None = None,
    ) -> None:
        """Initialize native MaxSim stage.

        Args:
            qdrant_client: Async Qdrant client for multi-stage search
            collection_name: Collection or alias with ColBERT multi-vectors
            default_prefetch_limit: Default candidates for MUVERA prefetch
            default_final_limit: Default final candidates after MaxSim
            normalization: Model-intrinsic normalization params (from manifest)

        """
        if normalization is None:
            msg = "normalization must be provided - use manifest.late_interaction.normalization"
            raise ValueError(msg)
        self._client = qdrant_client
        self._collection_name = collection_name
        self._default_prefetch_limit = default_prefetch_limit
        self._default_final_limit = default_final_limit
        self._normalization = normalization

        logger.info(
            "Native MaxSim stage initialized",
            collection=collection_name,
            prefetch_limit=default_prefetch_limit,
            final_limit=default_final_limit,
            per_token_sim_mean=self._normalization.per_token_mean,
            per_token_sim_std=self._normalization.per_token_std,
        )

    @property
    def client(self) -> AsyncQdrantClient:
        """Expose Qdrant client for direct queries."""
        return self._client

    @property
    def collection_name(self) -> str:
        """Expose collection name."""
        return self._collection_name

    @property
    def normalization(self) -> MaxSimNormalizationParams:
        """Expose normalization parameters for external MaxSim computation."""
        return self._normalization

    async def retrieve_and_rerank(
        self,
        query: NativeMaxSimQuery,
    ) -> list[NativeMaxSimCandidate]:
        """Execute combined MUVERA retrieval + ColBERT MaxSim reranking.

        This replaces both Stage 1 (MUVERA retrieval) and Stage 2 (MaxSim rerank)
        with a single Qdrant multi-stage query.

        Args:
            query: NativeMaxSimQuery with all required vectors

        Returns:
            Candidates sorted by MaxSim score (descending)

        """
        has_sparse = bool(query.sparse_indices and query.sparse_values)

        logger.debug(
            "Starting native MaxSim retrieval",
            prefetch_limit=query.prefetch_limit,
            final_limit=query.final_limit,
            has_sparse=has_sparse,
            filters=query.filters,
        )

        results = await self._execute_query(query, has_sparse=has_sparse)
        candidates = NativeMaxSimCandidate.from_results_batch(
            results,
            query.num_tokens,
            per_token_mean=self._normalization.per_token_mean,
            per_token_std=self._normalization.per_token_std,
        )

        logger.info(
            "Native MaxSim retrieval completed",
            candidates_returned=len(candidates),
            prefetch_limit=query.prefetch_limit,
            final_limit=query.final_limit,
        )

        return candidates

    async def _execute_query(
        self,
        query: NativeMaxSimQuery,
        *,
        has_sparse: bool,
    ) -> list[MultiStageSearchResult]:
        """Execute the appropriate Qdrant query based on sparse availability."""
        if has_sparse:
            multi_query = MultiStageQuery(
                muvera_fde=query.muvera_fde,
                colbert_tokens=query.colbert_tokens,
                sparse_indices=query.sparse_indices,
                sparse_values=query.sparse_values,
                prefetch_limit=query.prefetch_limit,
                final_limit=query.final_limit,
                filters=query.filters,
            )
            return await search_multistage(self._client, self._collection_name, multi_query)

        muvera_query = MuveraMaxSimQuery(
            muvera_fde=query.muvera_fde,
            colbert_tokens=query.colbert_tokens,
            prefetch_limit=query.prefetch_limit,
            final_limit=query.final_limit,
            filters=query.filters,
        )
        return await search_muvera_then_maxsim(
            self._client,
            self._collection_name,
            muvera_query,
        )

    async def retrieve_and_rerank_from_retrieval_candidates(
        self,
        query: NativeMaxSimQuery,
        candidates: list[RetrievalCandidate],
    ) -> list[NativeMaxSimCandidate]:
        """Execute MaxSim reranking on pre-retrieved candidates.

        Performs a fresh multi-stage search but uses the candidate entity_ids
        to scope results.

        Args:
            query: NativeMaxSimQuery with all required vectors
            candidates: Pre-retrieved candidates whose entity_ids scope the search

        Returns:
            Candidates sorted by MaxSim score (descending)

        """
        if not candidates:
            return []

        entity_ids = [c.entity_id for c in candidates]
        return await self.score_by_entity_ids(query, entity_ids)

    async def score_by_entity_ids(
        self,
        query: NativeMaxSimQuery,
        entity_ids: list[str],
    ) -> list[NativeMaxSimCandidate]:
        """Score specific listings by entity_id with real embedding similarity.

        Used for backfill: computes real MaxSim scores for known listings.

        Args:
            query: NativeMaxSimQuery with profile embeddings
            entity_ids: List of listing entity_ids to score

        Returns:
            Candidates with real MaxSim scores for the specified listings

        """
        if not entity_ids:
            return []

        filtered_query = NativeMaxSimQuery(
            muvera_fde=query.muvera_fde,
            colbert_tokens=query.colbert_tokens,
            sparse_indices=query.sparse_indices,
            sparse_values=query.sparse_values,
            filters={"entity_id": entity_ids},
            prefetch_limit=len(entity_ids),
            final_limit=len(entity_ids),
        )

        logger.info(
            "Scoring specific listings by entity_id",
            num_listings=len(entity_ids),
            collection=self._collection_name,
        )

        return await self.retrieve_and_rerank(filtered_query)


@dataclass(frozen=True, slots=True)
class NativeMaxSimQueryParams:
    """Additional parameters for native MaxSim query."""

    prefetch_limit: int = 200
    final_limit: int = DEFAULT_STAGE2_LIMIT
    filters: dict[str, Any] | None = None


def build_native_maxsim_query(
    muvera_fde: list[float],
    colbert_tokens: list[list[float]],
    sparse_indices: list[int],
    sparse_values: list[float],
    params: NativeMaxSimQueryParams | None = None,
) -> NativeMaxSimQuery:
    """Build NativeMaxSimQuery from component parts.

    Args:
        muvera_fde: MUVERA FDE vector (for retrieval)
        colbert_tokens: ColBERT token embeddings as nested list
        sparse_indices: Sparse vector indices
        sparse_values: Sparse vector values
        params: Optional query parameters (limits, filters)

    Returns:
        NativeMaxSimQuery ready for stage execution

    """
    params = params or NativeMaxSimQueryParams()
    return NativeMaxSimQuery(
        muvera_fde=muvera_fde,
        colbert_tokens=colbert_tokens,
        sparse_indices=sparse_indices,
        sparse_values=sparse_values,
        prefetch_limit=params.prefetch_limit,
        final_limit=params.final_limit,
        filters=params.filters,
    )

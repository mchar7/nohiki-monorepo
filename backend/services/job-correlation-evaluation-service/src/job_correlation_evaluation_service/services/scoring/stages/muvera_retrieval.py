"""Stage 1: MUVERA ANN Retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nohiki_observability import get_logger
from nohiki_qdrant_client import SearchParams

if TYPE_CHECKING:
    from nohiki_qdrant_client import QdrantVectorClient

logger = get_logger(__name__)

DEFAULT_STAGE1_LIMIT = 1000


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """Query parameters for MUVERA retrieval."""

    muvera_fde: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    filters: dict[str, Any] | None = None
    limit: int | None = None
    score_threshold: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """Candidate from Stage 1 MUVERA retrieval."""

    entity_id: str
    muvera_score: float
    payload: dict[str, Any]


class MuveraRetrievalStage:
    """Stage 1: MUVERA ANN retrieval via Qdrant hybrid search.

    Uses MUVERA FDE + Sparse vectors with RRF fusion for fast
    approximate nearest neighbor retrieval.

    Pipeline Position:
        Stage 1: MUVERA ANN (Qdrant)     → ~1000 candidates   ← THIS STAGE
        Stage 2: MaxSim Rerank           → ~150 candidates
        Stage 3: LLM Rerank (optional)   → ~50 candidates
        Stage 4: L2R Final Ranking       → Final ranked list

    Search Strategy:
        - Hybrid search: MUVERA FDE (semantic) + Sparse (keyword)
        - RRF fusion combines results from both indexes
        - Fallback to MUVERA-only if sparse vectors unavailable

    """

    def __init__(
        self,
        qdrant_client: QdrantVectorClient,
        collection_name: str,
        default_limit: int = DEFAULT_STAGE1_LIMIT,
    ) -> None:
        """Initialize MUVERA retrieval stage.

        Args:
            qdrant_client: Qdrant vector client for hybrid search
            collection_name: Qdrant collection name (derived from manifest)
            default_limit: Default max candidates to retrieve (default 1000)

        """
        self._qdrant = qdrant_client
        self._collection_name = collection_name
        self._default_limit = default_limit

        logger.info(
            "MUVERA retrieval stage initialized",
            collection_name=collection_name,
            default_limit=default_limit,
        )

    async def retrieve(
        self,
        query: RetrievalQuery,
    ) -> list[RetrievalCandidate]:
        """Retrieve candidates using MUVERA + Sparse hybrid search.

        Args:
            query: RetrievalQuery with MUVERA FDE, sparse vectors, and options

        Returns:
            List of RetrievalCandidate with muvera_score and payload

        """
        effective_limit = query.limit or self._default_limit

        # Determine search method based on sparse availability
        has_sparse = bool(query.sparse_indices and query.sparse_values)

        logger.debug(
            "Starting MUVERA retrieval",
            limit=effective_limit,
            has_sparse=has_sparse,
            filters=query.filters,
        )

        if has_sparse:
            results = await self._qdrant.search_hybrid(
                query_muvera_fde=query.muvera_fde,
                query_sparse_indices=query.sparse_indices,
                query_sparse_values=query.sparse_values,
                params=SearchParams(
                    collection_name=self._collection_name,
                    limit=effective_limit,
                    filters=query.filters,
                    score_threshold=query.score_threshold,
                ),
            )
        else:
            # Fallback to MUVERA-only search
            logger.warning("Sparse vectors not available, using MUVERA-only search")
            results = await self._qdrant.search_muvera_only(
                collection_name=self._collection_name,
                query_muvera_fde=query.muvera_fde,
                limit=effective_limit,
                filters=query.filters,
                score_threshold=query.score_threshold,
            )

        candidates = [
            RetrievalCandidate(
                entity_id=r.id,
                muvera_score=r.score,
                payload=r.payload,
            )
            for r in results
        ]

        logger.info(
            "MUVERA retrieval completed",
            candidates_returned=len(candidates),
            limit=effective_limit,
        )

        return candidates

    async def retrieve_by_ids(
        self,
        entity_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Retrieve payloads for specific entity IDs via batch API.

        Uses Qdrant's native batch retrieve (single network call) instead
        of N individual requests.

        Args:
            entity_ids: List of entity IDs to retrieve

        Returns:
            Dict mapping entity_id to payload

        """
        if not entity_ids:
            return {}

        return await self._qdrant.get_points_batch(self._collection_name, entity_ids)

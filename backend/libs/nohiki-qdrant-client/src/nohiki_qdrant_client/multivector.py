"""Multi-vector support for Qdrant (ColBERT MaxSim reranking).

Native Qdrant multi-stage search using:
- Stage 1: MUVERA FDE for fast initial retrieval (approximate)
- Stage 2: ColBERT MaxSim for precise reranking (exact)

Benefits over external MaxSim computation:
- Eliminates S3/Redis round-trips for token retrieval
- Qdrant's MaxSim is SIMD-optimized in Rust
- Single network call for entire search pipeline

Trade-offs:
- ~20x storage increase vs MUVERA-only (full ColBERT tokens in Qdrant)
- Use on-disk storage for cost efficiency on large collections

Usage:
    config = MultiVectorCollectionConfig(
        semantic_repr_id="jobs.semantic_repr.v1",
        entity_type="jobs",
        muvera_dim=8192,
        colbert_dim=48,
    )
    await create_multivector_collection(client, config)

    # Upsert with ColBERT tokens
    await upsert_multivector_point(
        client, "jobs_active", point_id,
        muvera_fde, sparse_indices, sparse_values, colbert_tokens, payload
    )

    # Multi-stage search
    results = await search_multistage(
        client, "jobs_active", query_muvera, query_colbert, query_sparse, ...
    )
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nohiki_observability import get_logger
from qdrant_client import models

from nohiki_qdrant_client.collections import (
    PAYLOAD_INDEX_SCHEMAS,
    _create_or_update_alias_async,
    get_collection_name,
)
from nohiki_qdrant_client.filter_builder import build_filter

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MultiVectorCollectionConfig:
    """Configuration for creating a multi-vector Qdrant collection."""

    semantic_repr_id: str
    entity_type: str
    muvera_dim: int
    colbert_dim: int
    distance_metric: str = "Dot"
    alias_name: str | None = None
    on_disk: bool = True
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100
    colbert_on_disk: bool = True


@dataclass(frozen=True, slots=True)
class MultiStageSearchResult:
    """Result from multi-stage search with MaxSim score."""

    id: str
    muvera_score: float
    maxsim_score: float
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MultiVectorPoint:
    """Data for upserting a multi-vector point."""

    point_id: str
    muvera_fde: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    colbert_tokens: list[list[float]]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MultiStageQuery:
    """Query parameters for multi-stage search."""

    muvera_fde: list[float]
    colbert_tokens: list[list[float]]
    sparse_indices: list[int]
    sparse_values: list[float]
    prefetch_limit: int = 200
    final_limit: int = 50
    filters: dict[str, Any] | None = None
    score_threshold: float | None = None


@dataclass(frozen=True, slots=True)
class MuveraMaxSimQuery:
    """Query parameters for MUVERA → MaxSim two-stage search."""

    muvera_fde: list[float]
    colbert_tokens: list[list[float]]
    prefetch_limit: int = 200
    final_limit: int = 50
    filters: dict[str, Any] | None = None


DISTANCE_METRICS: dict[str, models.Distance] = {
    "Dot": models.Distance.DOT,
    "Cosine": models.Distance.COSINE,
    "Euclid": models.Distance.EUCLID,
}


async def create_multivector_collection(
    client: AsyncQdrantClient,
    config: MultiVectorCollectionConfig,
) -> str:
    """Create Qdrant collection with MUVERA, Sparse, and ColBERT multi-vectors.

    This enables native multi-stage search with MUVERA → ColBERT MaxSim reranking.

    Args:
        client: Async Qdrant client
        config: Collection configuration

    Returns:
        Collection name

    """
    collection_name = get_collection_name(config.entity_type, config.semantic_repr_id)
    distance = DISTANCE_METRICS.get(config.distance_metric, models.Distance.DOT)

    await client.recreate_collection(
        collection_name=collection_name,
        vectors_config={
            "muvera": models.VectorParams(
                size=config.muvera_dim,
                distance=distance,
                on_disk=config.on_disk,
                hnsw_config=models.HnswConfigDiff(
                    m=config.hnsw_m,
                    ef_construct=config.hnsw_ef_construct,
                ),
            ),
            "colbert": models.VectorParams(
                size=config.colbert_dim,
                distance=models.Distance.COSINE,
                on_disk=config.colbert_on_disk,
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM,
                ),
                hnsw_config=models.HnswConfigDiff(m=0),
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(
                    full_scan_threshold=100_000,
                ),
            ),
        },
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8,
                quantile=0.99,
                always_ram=False,
            ),
        ),
        on_disk_payload=True,
    )

    async with asyncio.TaskGroup() as tg:
        for field, schema in PAYLOAD_INDEX_SCHEMAS:
            tg.create_task(
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field,
                    field_schema=schema,
                )
            )

    if config.alias_name:
        await _create_or_update_alias_async(client, config.alias_name, collection_name)

    logger.info(
        "Multi-vector collection created",
        collection=collection_name,
        muvera_dim=config.muvera_dim,
        colbert_dim=config.colbert_dim,
        distance=config.distance_metric,
        alias=config.alias_name,
    )

    return collection_name


async def upsert_multivector_point(
    client: AsyncQdrantClient,
    collection_name: str,
    point: MultiVectorPoint,
) -> None:
    """Upsert a point with MUVERA FDE, sparse vector, and ColBERT multi-vectors.

    Args:
        client: Async Qdrant client
        collection_name: Target collection
        point: Multi-vector point data

    """
    await client.upsert(
        collection_name=collection_name,
        points=[
            models.PointStruct(
                id=point.point_id,
                vector={
                    "muvera": point.muvera_fde,
                    "colbert": point.colbert_tokens,
                    "sparse": models.SparseVector(
                        indices=point.sparse_indices,
                        values=point.sparse_values,
                    ),
                },
                payload=point.payload,
            ),
        ],
    )

    logger.debug(
        "Multi-vector point upserted",
        point_id=point.point_id,
        num_colbert_tokens=len(point.colbert_tokens),
    )


async def search_multistage(
    client: AsyncQdrantClient,
    collection_name: str,
    query: MultiStageQuery,
) -> list[MultiStageSearchResult]:
    """Multi-stage search: MUVERA+Sparse → ColBERT MaxSim reranking.

    Stage 1: Hybrid MUVERA+Sparse retrieval with RRF fusion
    Stage 2: ColBERT MaxSim reranking of top candidates

    This is the recommended search pattern for best precision with
    all semantic representations indexed in Qdrant.

    Args:
        client: Async Qdrant client
        collection_name: Collection or alias name
        query: Multi-stage query parameters

    Returns:
        List of search results with MaxSim scores

    """
    qdrant_filter = build_filter(query.filters) if query.filters else None

    results = await client.query_points(
        collection_name=collection_name,
        prefetch=[
            models.Prefetch(
                query=query.muvera_fde,
                using="muvera",
                limit=query.prefetch_limit,
                filter=qdrant_filter,
            ),
            models.Prefetch(
                query=models.SparseVector(
                    indices=query.sparse_indices,
                    values=query.sparse_values,
                ),
                using="sparse",
                limit=query.prefetch_limit,
                filter=qdrant_filter,
            ),
        ],
        query=query.colbert_tokens,
        using="colbert",
        limit=query.final_limit,
        score_threshold=query.score_threshold,
        with_payload=True,
    )

    # Get MUVERA scores for the final candidates
    final_ids = [str(point.id) for point in results.points]
    if final_ids:
        muvera_results = await client.query_points(
            collection_name=collection_name,
            query=query.muvera_fde,
            using="muvera",
            limit=len(final_ids) * 2,  # Get enough to cover reranked results
            query_filter=qdrant_filter,
            with_payload=False,
        )
        muvera_scores: dict[str, float] = {str(point.id): point.score or 0.0 for point in muvera_results.points}
    else:
        muvera_scores = {}

    return [
        MultiStageSearchResult(
            id=str(point.id),
            muvera_score=muvera_scores.get(str(point.id), 0.0),
            maxsim_score=point.score or 0.0,
            payload=dict(point.payload) if point.payload else {},
        )
        for point in results.points
    ]


async def search_muvera_then_maxsim(
    client: AsyncQdrantClient,
    collection_name: str,
    query: MuveraMaxSimQuery,
) -> list[MultiStageSearchResult]:
    """Two-stage search: MUVERA retrieval → ColBERT MaxSim reranking.

    This performs TWO queries to capture BOTH similarity signals:
    1. MUVERA-only query to get approximate similarity scores
    2. Prefetch+rerank query to get precise MaxSim scores

    Both scores are important for the L2R model to differentiate candidates.

    Args:
        client: Async Qdrant client
        collection_name: Collection or alias name
        query: MUVERA + MaxSim query parameters

    Returns:
        List of search results with BOTH MUVERA and MaxSim scores

    """
    qdrant_filter = build_filter(query.filters) if query.filters else None

    # Both queries are independent: run concurrently via TaskGroup
    async with asyncio.TaskGroup() as tg:
        muvera_task = tg.create_task(
            client.query_points(
                collection_name=collection_name,
                query=query.muvera_fde,
                using="muvera",
                limit=query.prefetch_limit,
                query_filter=qdrant_filter,
                with_payload=False,
            )
        )
        maxsim_task = tg.create_task(
            client.query_points(
                collection_name=collection_name,
                prefetch=models.Prefetch(
                    query=query.muvera_fde,
                    using="muvera",
                    limit=query.prefetch_limit,
                    filter=qdrant_filter,
                ),
                query=query.colbert_tokens,
                using="colbert",
                limit=query.final_limit,
                with_payload=True,
            )
        )

    muvera_scores: dict[str, float] = {str(point.id): point.score or 0.0 for point in muvera_task.result().points}

    return [
        MultiStageSearchResult(
            id=str(point.id),
            muvera_score=muvera_scores.get(str(point.id), 0.0),
            maxsim_score=point.score or 0.0,
            payload=dict(point.payload) if point.payload else {},
        )
        for point in maxsim_task.result().points
    ]

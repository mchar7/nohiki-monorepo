"""Qdrant vector client for hybrid search (model-agnostic)."""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from nohiki.ml.v1 import EmbeddingType, EmbeddingVector
from nohiki_ml_manifest import QdrantCollectionSchema
from nohiki_observability import get_logger

from nohiki_qdrant_client.config import QdrantSettings

if TYPE_CHECKING:
    from qdrant_client.async_qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models

logger = get_logger(__name__)

type _PointIds = list[int | str | UUID]


def create_async_qdrant_client(settings: QdrantSettings) -> AsyncQdrantClient:
    """Create a raw ``AsyncQdrantClient`` from settings.

    Use this for operations that don't need schema awareness
    (health probes, collection management).

    Args:
        settings: Qdrant connection settings.

    Returns:
        Configured async Qdrant client using gRPC transport.

    """
    client_type = cast(
        "type[AsyncQdrantClient]",
        importlib.import_module("qdrant_client.async_qdrant_client").AsyncQdrantClient,
    )

    return client_type(
        host=settings.host,
        grpc_port=settings.grpc_port,
        prefer_grpc=True,
        https=settings.use_tls,
        api_key=(settings.api_key.get_secret_value() if settings.api_key else None),
        timeout=settings.timeout_seconds,
        # Disable background version check thread: it spawns a daemon thread
        # that calls warnings.warn() on connection failure, which becomes a
        # PytestUnhandledThreadExceptionWarning under filterwarnings=["error"].
        check_compatibility=False,
    )


_RESERVED_PAYLOAD_FIELDS = frozenset({"entity_id", "entity_type", "collection_version", "content_hash", "is_active"})


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    """Result from hybrid search."""

    id: str
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UpsertPayload:
    """Payload for upserting a point to Qdrant."""

    entity_id: str
    entity_type: str
    collection_version: str
    content_hash: str
    is_active: bool = True
    extra: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Reject incomplete payloads and reserved-field overrides."""
        for field_name in ("entity_id", "entity_type", "collection_version", "content_hash"):
            if not getattr(self, field_name).strip():
                msg = f"{field_name} must not be empty"
                raise ValueError(msg)
        if conflicts := _RESERVED_PAYLOAD_FIELDS.intersection(self.extra or {}):
            names = ", ".join(sorted(conflicts))
            msg = f"extra payload cannot override reserved fields: {names}"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Convert to Qdrant payload dict, merging extra fields."""
        base: dict[str, Any] = {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "collection_version": self.collection_version,
            "content_hash": self.content_hash,
            "is_active": self.is_active,
        }
        if self.extra:
            base |= self.extra
        return base


@dataclass(frozen=True, slots=True)
class SearchParams:
    """Parameters for vector search."""

    collection_name: str
    limit: int = 1000
    filters: dict[str, Any] | None = None
    score_threshold: float | None = None
    vector_name: str | None = None

    def __post_init__(self) -> None:
        """Validate parameters before issuing a Qdrant request."""
        if not self.collection_name.strip():
            msg = "collection_name must not be empty"
            raise ValueError(msg)
        if self.limit <= 0:
            msg = "limit must be greater than zero"
            raise ValueError(msg)
        if self.score_threshold is not None and not math.isfinite(self.score_threshold):
            msg = "score_threshold must be finite"
            raise ValueError(msg)
        if self.vector_name is not None and not self.vector_name.strip():
            msg = "vector_name must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class GroupedSearchParams(SearchParams):
    """Parameters for grouped vector search."""

    group_by: str = ""
    group_size: int = 1

    def __post_init__(self) -> None:
        """Validate grouped-search-specific parameters."""
        SearchParams.__post_init__(self)
        if not self.group_by.strip():
            msg = "group_by must not be empty"
            raise ValueError(msg)
        if self.group_size <= 0:
            msg = "group_size must be greater than zero"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class VectorPoint:
    """Topology-agnostic Qdrant point carrying typed EmbeddingVectors.

    The caller populates embeddings with whatever EmbeddingVector types
    the collection schema supports. QdrantVectorClient dispatches each
    vector to the correct named vector slot via EmbeddingType, using
    the collection schema configured at construction time.

    Attributes:
        point_id: Qdrant point identifier (string, not UUID object).
        embeddings: One or more EmbeddingVector instances to upsert.
        payload: Structured metadata payload for this point.

    """

    point_id: str
    embeddings: list[EmbeddingVector]
    payload: UpsertPayload


class QdrantVectorClient:
    """Async Qdrant client for hybrid search with MUVERA + Sparse + ColBERT vectors.

    Vector names are derived from ``QdrantCollectionSchema`` at construction time,
    providing a single source of truth from the manifest. The schema is required;
    use ``create_async_qdrant_client`` for schema-free operations like health probes.
    """

    __slots__ = (
        "_client_instance",
        "_colbert_name",
        "_primary_dense",
        "_schema",
        "_settings",
        "_sparse_name",
    )

    def __init__(
        self,
        settings: QdrantSettings,
        collection_schema: QdrantCollectionSchema,
    ) -> None:
        """Initialize Qdrant vector client.

        Args:
            settings: Qdrant connection settings.
            collection_schema: Collection schema from manifest defining
                vector names and their roles.

        """
        self._settings = settings
        self._schema = collection_schema
        self._primary_dense = collection_schema.primary_dense_name
        self._colbert_name = collection_schema.colbert_name
        self._sparse_name: str | None = collection_schema.sparse.name if collection_schema.sparse else None
        self._client_instance: AsyncQdrantClient | None = None

    @property
    def _client(self) -> AsyncQdrantClient:
        if self._client_instance is None:
            self._client_instance = create_async_qdrant_client(self._settings)
        return self._client_instance

    @property
    def raw_client(self) -> AsyncQdrantClient:
        """Get the underlying async Qdrant client for advanced operations."""
        return self._client

    @property
    def primary_dense_name(self) -> str:
        """Primary dense vector name derived from schema."""
        return self._primary_dense

    @property
    def sparse_name(self) -> str | None:
        """First sparse vector name from schema, or ``None`` if unavailable."""
        return self._sparse_name

    @staticmethod
    def _to_hybrid_result(point: models.ScoredPoint) -> HybridSearchResult:
        """Convert a Qdrant ScoredPoint to a HybridSearchResult."""
        return HybridSearchResult(
            id=str(point.id),
            score=point.score or 0.0,
            payload=dict(point.payload) if point.payload else {},
        )

    async def search_hybrid(
        self,
        query_muvera_fde: list[float],
        query_sparse_indices: list[int],
        query_sparse_values: list[float],
        params: SearchParams,
    ) -> list[HybridSearchResult]:
        """Hybrid search using MUVERA FDE + Sparse with RRF fusion.

        Args:
            query_muvera_fde: MUVERA FDE vector from query encoding.
            query_sparse_indices: Sparse vector indices.
            query_sparse_values: Sparse vector values.
            params: Search parameters.

        Returns:
            List of search results with scores and payloads.

        """
        filter_builder = importlib.import_module("nohiki_qdrant_client.filter_builder")
        qdrant_models = importlib.import_module("qdrant_client.models")
        qdrant_filter = filter_builder.build_filter(params.filters) if params.filters else None
        if self._sparse_name is None:
            msg = "Hybrid search requires a sparse vector in the collection schema"
            raise ValueError(msg)

        results = await self._client.query_points(
            collection_name=params.collection_name,
            prefetch=[
                qdrant_models.Prefetch(
                    query=query_muvera_fde,
                    using=self._primary_dense,
                    limit=params.limit,
                    filter=qdrant_filter,
                ),
                qdrant_models.Prefetch(
                    query=qdrant_models.SparseVector(
                        indices=query_sparse_indices,
                        values=query_sparse_values,
                    ),
                    using=self._sparse_name,
                    limit=params.limit,
                    filter=qdrant_filter,
                ),
            ],
            query=qdrant_models.FusionQuery(fusion=qdrant_models.Fusion.RRF),
            limit=params.limit,
            score_threshold=params.score_threshold,
            with_payload=True,
        )

        return [self._to_hybrid_result(p) for p in results.points]

    async def search_muvera_only(
        self,
        collection_name: str,
        query_muvera_fde: list[float],
        limit: int = 1000,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[HybridSearchResult]:
        """MUVERA-only search (fallback when sparse not available).

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            query_muvera_fde: MUVERA FDE vector from query encoding.
            limit: Max results to return.
            filters: Payload filters (e.g., ``{"is_active": True}``).
            score_threshold: Min score threshold.

        Returns:
            List of search results with scores and payloads.

        """
        filter_builder = importlib.import_module("nohiki_qdrant_client.filter_builder")
        qdrant_filter = filter_builder.build_filter(filters) if filters else None

        results = await self._client.query_points(
            collection_name=collection_name,
            query=query_muvera_fde,
            using=self._primary_dense,
            limit=limit,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [self._to_hybrid_result(p) for p in results.points]

    @staticmethod
    def _validate_finite_vector(values: list[float], *, label: str) -> None:
        if not values:
            msg = f"{label} must not be empty"
            raise ValueError(msg)
        if not all(math.isfinite(value) for value in values):
            msg = f"{label} must contain only finite values"
            raise ValueError(msg)

    def _dense_vector_entry(self, emb: EmbeddingVector, point_id: str) -> tuple[str, list[float]]:
        if emb.dense is None:
            msg = f"EmbeddingType {emb.embedding_type.name} has no DenseData for point {point_id!r}"
            raise ValueError(msg)
        values = list(emb.dense.values)
        self._validate_finite_vector(values, label=f"dense embedding for point {point_id!r}")
        return self._primary_dense, values

    def _sparse_vector_entry(self, emb: EmbeddingVector, point_id: str) -> tuple[str, models.SparseVector]:
        if emb.sparse is None:
            msg = f"EmbeddingType.SPARSE has no SparseData for point {point_id!r}"
            raise ValueError(msg)
        if self._sparse_name is None:
            msg = f"Collection schema has no sparse vector - cannot upsert SPARSE for {point_id!r}"
            raise ValueError(msg)
        indices = list(emb.sparse.indices)
        values = list(emb.sparse.values)
        if not indices or len(indices) != len(values):
            msg = f"sparse indices and values must have equal non-zero lengths for {point_id!r}"
            raise ValueError(msg)
        if any(index < 0 for index in indices) or len(set(indices)) != len(indices):
            msg = f"sparse indices must be unique and non-negative for {point_id!r}"
            raise ValueError(msg)
        self._validate_finite_vector(values, label=f"sparse embedding for point {point_id!r}")
        qdrant_models = importlib.import_module("qdrant_client.models")
        return self._sparse_name, qdrant_models.SparseVector(indices=indices, values=values)

    def _colbert_vector_entry(self, emb: EmbeddingVector, point_id: str) -> tuple[str, list[list[float]]]:
        if emb.multi_vector is None:
            msg = f"EmbeddingType.COLBERT has no MultiVectorData for point {point_id!r}"
            raise ValueError(msg)
        if self._colbert_name is None:
            msg = f"Collection schema has no ColBERT vector - cannot upsert COLBERT for {point_id!r}"
            raise ValueError(msg)
        n = emb.multi_vector.num_tokens
        d = emb.multi_vector.token_dim
        flat = list(emb.multi_vector.values)
        if n <= 0 or d <= 0 or len(flat) != n * d:
            msg = f"ColBERT shape does not match flattened values for {point_id!r}"
            raise ValueError(msg)
        self._validate_finite_vector(flat, label=f"ColBERT embedding for point {point_id!r}")
        return self._colbert_name, [flat[i * d : (i + 1) * d] for i in range(n)]

    def _embedding_to_vector_entry(
        self,
        emb: EmbeddingVector,
        point_id: str,
    ) -> tuple[str, list[float] | list[list[float]] | models.SparseVector]:
        """Dispatch an EmbeddingVector to its validated schema slot."""
        match emb.embedding_type:
            case EmbeddingType.DENSE | EmbeddingType.MUVERA:
                return self._dense_vector_entry(emb, point_id)
            case EmbeddingType.SPARSE:
                return self._sparse_vector_entry(emb, point_id)
            case EmbeddingType.COLBERT:
                return self._colbert_vector_entry(emb, point_id)
            case _:
                msg = f"Unrecognized EmbeddingType {emb.embedding_type!r} for point {point_id!r}"
                raise ValueError(msg)

    def _build_point_struct(self, point: VectorPoint) -> models.PointStruct:
        """Convert VectorPoint to Qdrant PointStruct using schema-driven dispatch.

        Args:
            point: Topology-agnostic point with typed embeddings and payload.

        Returns:
            PointStruct ready for Qdrant async upsert.

        Raises:
            ValueError: If any embedding has no data, an unrecognized type,
                or the collection schema lacks the required vector slot.

        """
        if not point.point_id.strip():
            msg = "point_id must not be empty"
            raise ValueError(msg)
        if not point.embeddings:
            msg = f"point {point.point_id!r} must contain at least one embedding"
            raise ValueError(msg)
        vectors: dict[str, list[float] | list[list[float]] | models.SparseVector] = {}
        for embedding in point.embeddings:
            name, vector = self._embedding_to_vector_entry(embedding, point.point_id)
            if name in vectors:
                msg = f"point {point.point_id!r} contains duplicate vector slot {name!r}"
                raise ValueError(msg)
            vectors[name] = vector
        qdrant_models = importlib.import_module("qdrant_client.models")
        return qdrant_models.PointStruct(
            id=point.point_id,
            vector=cast("models.VectorStruct", vectors),
            payload=point.payload.to_dict(),
        )

    async def upsert_vector_point(
        self,
        collection_name: str,
        point: VectorPoint,
    ) -> None:
        """Upsert a single topology-agnostic VectorPoint to Qdrant.

        Args:
            collection_name: Target Qdrant collection name.
            point: VectorPoint with typed embeddings and payload.

        Raises:
            ValueError: If any embedding has no data or unrecognized type.

        """
        struct = self._build_point_struct(point)
        await self._client.upsert(
            collection_name=collection_name,
            points=[struct],
            wait=True,
        )
        logger.debug(
            "Vector point upserted",
            point_id=point.point_id,
            collection_name=collection_name,
            content_hash=point.payload.content_hash,
        )

    async def upsert_vector_points_batch(
        self,
        collection_name: str,
        points: list[VectorPoint],
        batch_size: int = 100,
    ) -> int:
        """Upsert multiple VectorPoints to Qdrant in contiguous batches.

        Processes all points in chunks of batch_size to avoid overwhelming
        Qdrant with very large payloads. Each chunk is awaited before the next.

        Args:
            collection_name: Target Qdrant collection name.
            points: VectorPoints to upsert (may be empty: returns 0).
            batch_size: Points per Qdrant upsert call. Default 100.

        Returns:
            Total number of points successfully upserted.

        Raises:
            ValueError: If any point has invalid embedding data.

        """
        if batch_size <= 0:
            msg = "batch_size must be greater than zero"
            raise ValueError(msg)
        if not points:
            return 0
        structs = [self._build_point_struct(p) for p in points]
        upserted = 0
        for i in range(0, len(structs), batch_size):
            chunk = structs[i : i + batch_size]
            await self._client.upsert(
                collection_name=collection_name,
                points=chunk,
                wait=True,
            )
            upserted += len(chunk)
        logger.info(
            "Vector batch upsert completed",
            collection_name=collection_name,
            total_upserted=upserted,
        )
        return upserted

    async def search_dense(
        self,
        query_vector: list[float],
        params: SearchParams,
    ) -> list[HybridSearchResult]:
        """Search for dense vectors in collections with single dense vector indexes.

        Used for skill embeddings and other single-vector use cases.

        Args:
            query_vector: Dense embedding vector.
            params: Search parameters.

        Returns:
            List of search results with scores and payloads.

        """
        filter_builder = importlib.import_module("nohiki_qdrant_client.filter_builder")
        qdrant_filter = filter_builder.build_filter(params.filters) if params.filters else None
        vector_name = params.vector_name or self._primary_dense

        results = await self._client.query_points(
            collection_name=params.collection_name,
            query=query_vector,
            using=vector_name,
            limit=params.limit,
            query_filter=qdrant_filter,
            score_threshold=params.score_threshold,
            with_payload=True,
        )

        return [self._to_hybrid_result(p) for p in results.points]

    async def search_dense_batch(
        self,
        queries: list[list[float]],
        params: SearchParams,
    ) -> list[list[HybridSearchResult]]:
        """Batch dense search: all queries in a single Qdrant network round-trip.

        Args:
            queries: Dense embedding vectors, one per query.
            params: Shared search parameters applied to all queries.

        Returns:
            List of result lists, one per input query, in the same order.

        """
        if not queries:
            return []

        vector_name = params.vector_name or self._primary_dense
        filter_builder = importlib.import_module("nohiki_qdrant_client.filter_builder")
        qdrant_models = importlib.import_module("qdrant_client.models")
        qdrant_filter = filter_builder.build_filter(params.filters) if params.filters else None
        requests = [
            qdrant_models.QueryRequest(
                query=query,
                using=vector_name,
                limit=params.limit,
                filter=qdrant_filter,
                score_threshold=params.score_threshold,
                with_payload=True,
            )
            for query in queries
        ]

        batch_response = await self._client.query_batch_points(
            collection_name=params.collection_name,
            requests=requests,
        )
        return [[self._to_hybrid_result(p) for p in r.points] for r in batch_response]

    async def get_point(
        self,
        collection_name: str,
        point_id: str,
    ) -> dict[str, Any] | None:
        """Get single point payload by ID.

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            point_id: Point ID to retrieve.

        Returns:
            Point payload dict or None if not found.

        """
        points = await self._client.retrieve(
            collection_name=collection_name,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        return dict(points[0].payload) if points[0].payload else {}

    async def get_points_batch(
        self,
        collection_name: str,
        point_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch retrieve payloads for multiple point IDs in a single network call.

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            point_ids: List of point IDs to retrieve.

        Returns:
            Dict mapping point_id to payload dict. Missing points are omitted.

        """
        if not point_ids:
            return {}

        points = await self._client.retrieve(
            collection_name=collection_name,
            ids=cast("_PointIds", point_ids),
            with_payload=True,
            with_vectors=False,
        )

        return {str(point.id): dict(point.payload) if point.payload else {} for point in points}

    async def point_exists(
        self,
        collection_name: str,
        point_id: str,
    ) -> bool:
        """Check if a point exists.

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            point_id: Point ID to check.

        Returns:
            True if point exists.

        """
        return await self.get_point(collection_name, point_id) is not None

    async def delete_points(
        self,
        collection_name: str,
        point_ids: list[str],
    ) -> None:
        """Delete points by ID.

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            point_ids: List of point IDs to delete.

        """
        qdrant_models = importlib.import_module("qdrant_client.models")
        await self._client.delete(
            collection_name=collection_name,
            points_selector=qdrant_models.PointIdsList(points=cast("_PointIds", point_ids)),
        )
        logger.debug("Points deleted", collection_name=collection_name, count=len(point_ids))

    async def set_points_inactive(
        self,
        collection_name: str,
        point_ids: list[str],
    ) -> None:
        """Mark points as inactive (soft delete).

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            point_ids: List of point IDs to mark inactive.

        """
        qdrant_models = importlib.import_module("qdrant_client.models")
        await self._client.set_payload(
            collection_name=collection_name,
            payload={"is_active": False},
            points=qdrant_models.PointIdsList(points=cast("_PointIds", point_ids)),
        )
        logger.debug("Points marked inactive", collection_name=collection_name, count=len(point_ids))

    async def search_grouped(
        self,
        query_vector: list[float],
        params: GroupedSearchParams,
    ) -> list[HybridSearchResult]:
        """Search with grouping to deduplicate results by a payload field.

        Uses Qdrant's native group_by feature instead of Python-side deduplication.
        Returns the best match per group (e.g., best embedding variant per skill_id).

        Args:
            query_vector: Dense embedding vector.
            params: Grouped search parameters.

        Returns:
            List of search results, one per group (best match).

        """
        filter_builder = importlib.import_module("nohiki_qdrant_client.filter_builder")
        qdrant_filter = filter_builder.build_filter(params.filters) if params.filters else None
        vector_name = params.vector_name or self._primary_dense

        results = await self._client.query_points_groups(
            collection_name=params.collection_name,
            query=query_vector,
            using=vector_name,
            group_by=params.group_by,
            limit=params.limit,
            group_size=params.group_size,
            query_filter=qdrant_filter,
            score_threshold=params.score_threshold,
            with_payload=True,
        )

        return [self._to_hybrid_result(hit) for group in results.groups for hit in group.hits]

    async def retrieve_vectors(
        self,
        collection_name: str,
        point_ids: list[str],
        vector_name: str | None = None,
    ) -> dict[str, list[float]]:
        """Batch retrieve dense vectors by point ID.

        Args:
            collection_name: Qdrant collection name.
            point_ids: List of point IDs to retrieve.
            vector_name: Named vector to retrieve. If None, uses primary dense name.

        Returns:
            Dict mapping point_id to vector values. Missing points are omitted.

        """
        if not point_ids:
            return {}

        points = await self._client.retrieve(
            collection_name=collection_name,
            ids=cast("_PointIds", point_ids),
            with_vectors=True,
            with_payload=False,
        )

        effective_name = vector_name or self._primary_dense
        return {
            str(point.id): vec
            for point in points
            if (vec := self._extract_vector(point.vector, effective_name)) is not None
        }

    @staticmethod
    def _extract_vector(raw: object, vector_name: str | None) -> list[float] | None:
        """Extract and validate a named or default dense vector."""
        candidate: object = raw.get(vector_name or "") if isinstance(raw, dict) else raw
        if not isinstance(candidate, list):
            return None
        vector: list[float] = []
        for value in candidate:
            if not isinstance(value, int | float):
                return None
            vector.append(float(value))
        return vector

    async def count_points(
        self,
        collection_name: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count points matching filters.

        Args:
            collection_name: Qdrant collection name (derived from manifest).
            filters: Optional payload filters.

        Returns:
            Number of matching points.

        """
        filter_builder = importlib.import_module("nohiki_qdrant_client.filter_builder")
        qdrant_filter = filter_builder.build_filter(filters) if filters else None

        result = await self._client.count(
            collection_name=collection_name,
            count_filter=qdrant_filter,
            exact=True,
        )
        return int(result.count)

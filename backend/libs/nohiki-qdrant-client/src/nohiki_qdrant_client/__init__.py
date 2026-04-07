"""Qdrant vector client for MUVERA + Sparse + ColBERT multi-vector search.

Provides a schema-driven Qdrant client where vector names and roles are
derived from ``QdrantCollectionSchema`` at construction time.

Usage::

    from nohiki_qdrant_client import QdrantVectorClient, QdrantSettings, SearchParams

    settings = QdrantSettings(host="localhost")
    client = QdrantVectorClient(settings, collection_schema=schema)
    results = await client.search_hybrid(
        query_muvera_fde=[0.1] * 8192,
        query_sparse_indices=[1, 5, 10],
        query_sparse_values=[0.5, 0.3, 0.2],
        params=SearchParams(collection_name="jobs_v1"),
    )
"""

from nohiki_qdrant_client.client import (
    GroupedSearchParams,
    HybridSearchResult,
    QdrantVectorClient,
    SearchParams,
    UpsertPayload,
    VectorPoint,
    create_async_qdrant_client,
)
from nohiki_qdrant_client.collections import PAYLOAD_INDEX_SCHEMAS, CollectionConfig
from nohiki_qdrant_client.config import QdrantMixin, QdrantSettings
from nohiki_qdrant_client.filter_builder import build_filter, build_filter_with_should
from nohiki_qdrant_client.health import QdrantHealthProbe, ensure_qdrant_ready
from nohiki_qdrant_client.multivector import (
    MultiStageQuery,
    MultiStageSearchResult,
    MultiVectorCollectionConfig,
    MultiVectorPoint,
    MuveraMaxSimQuery,
)

__all__ = [
    "PAYLOAD_INDEX_SCHEMAS",
    "CollectionConfig",
    "GroupedSearchParams",
    "HybridSearchResult",
    "MultiStageQuery",
    "MultiStageSearchResult",
    "MultiVectorCollectionConfig",
    "MultiVectorPoint",
    "MuveraMaxSimQuery",
    "QdrantHealthProbe",
    "QdrantMixin",
    "QdrantSettings",
    "QdrantVectorClient",
    "SearchParams",
    "UpsertPayload",
    "VectorPoint",
    "build_filter",
    "build_filter_with_should",
    "create_async_qdrant_client",
    "ensure_qdrant_ready",
]

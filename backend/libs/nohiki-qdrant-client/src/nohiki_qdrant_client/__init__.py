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

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from nohiki_qdrant_client.client import (
    GroupedSearchParams,
    HybridSearchResult,
    QdrantVectorClient,
    SearchParams,
    UpsertPayload,
    VectorPoint,
    create_async_qdrant_client,
)
from nohiki_qdrant_client.config import QdrantMixin, QdrantSettings
from nohiki_qdrant_client.health import QdrantHealthProbe, ensure_qdrant_ready

if TYPE_CHECKING:
    from nohiki_qdrant_client.collections import PAYLOAD_INDEX_SCHEMAS as PAYLOAD_INDEX_SCHEMAS
    from nohiki_qdrant_client.collections import CollectionConfig as CollectionConfig
    from nohiki_qdrant_client.filter_builder import build_filter as build_filter
    from nohiki_qdrant_client.filter_builder import build_filter_with_should as build_filter_with_should
    from nohiki_qdrant_client.multivector import MultiStageQuery as MultiStageQuery
    from nohiki_qdrant_client.multivector import MultiStageSearchResult as MultiStageSearchResult
    from nohiki_qdrant_client.multivector import MultiVectorCollectionConfig as MultiVectorCollectionConfig
    from nohiki_qdrant_client.multivector import MultiVectorPoint as MultiVectorPoint
    from nohiki_qdrant_client.multivector import MuveraMaxSimQuery as MuveraMaxSimQuery

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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "PAYLOAD_INDEX_SCHEMAS": ("nohiki_qdrant_client.collections", "PAYLOAD_INDEX_SCHEMAS"),
    "CollectionConfig": ("nohiki_qdrant_client.collections", "CollectionConfig"),
    "build_filter": ("nohiki_qdrant_client.filter_builder", "build_filter"),
    "build_filter_with_should": ("nohiki_qdrant_client.filter_builder", "build_filter_with_should"),
    "MultiStageQuery": ("nohiki_qdrant_client.multivector", "MultiStageQuery"),
    "MultiStageSearchResult": ("nohiki_qdrant_client.multivector", "MultiStageSearchResult"),
    "MultiVectorCollectionConfig": ("nohiki_qdrant_client.multivector", "MultiVectorCollectionConfig"),
    "MultiVectorPoint": ("nohiki_qdrant_client.multivector", "MultiVectorPoint"),
    "MuveraMaxSimQuery": ("nohiki_qdrant_client.multivector", "MuveraMaxSimQuery"),
}


def __getattr__(name: str) -> object:
    """Lazy-import collection, filter, and multivector helpers (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

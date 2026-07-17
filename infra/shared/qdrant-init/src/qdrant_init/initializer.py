"""Collection initialization logic using manifest configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

import structlog

from qdrant_init.client import QdrantAPIError, QdrantConnectionError, QdrantInitClient

if TYPE_CHECKING:
    from nohiki_ml_manifest import CollectionConfig, SemanticRepresentationManifest

# Qdrant REST API payload types
#
# TypedDicts that precisely describe the Qdrant collection-creation payload,
# so _build_payload consumers (including tests) get native type safety
# without casts or workarounds.

type _VectorFieldValue = int | str | bool | dict[str, str]
"""Union of possible values in a single named-vector definition dict."""


class _SparseIndexConfig(TypedDict):
    """Sparse vector index threshold in a Qdrant collection payload."""

    full_scan_threshold: int


class _SparseVectorEntry(TypedDict):
    """Single sparse vector configuration in a Qdrant collection payload."""

    index: _SparseIndexConfig


class QdrantCollectionPayload(TypedDict, total=False):
    """Type-safe Qdrant REST API collection creation payload.

    Both fields use ``total=False`` because ``sparse_vectors`` is only
    present for collections that use sparse retrieval (e.g. jobs, profiles).
    """

    vectors: dict[str, dict[str, _VectorFieldValue]]
    sparse_vectors: dict[str, _SparseVectorEntry]


logger = structlog.get_logger(__name__)


@dataclass
class InitializationResult:
    """Result of collection initialization."""

    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True if no failures occurred."""
        return len(self.failed) == 0

    @property
    def total(self) -> int:
        """Return total number of collections processed."""
        return len(self.created) + len(self.skipped) + len(self.failed)


class CollectionInitializer:
    """Initializes Qdrant collections from semantic representation manifest."""

    def __init__(self, client: QdrantInitClient, manifest: SemanticRepresentationManifest) -> None:
        """Initialize with Qdrant client and manifest."""
        self._client = client
        self._manifest = manifest

    def initialize_all(self, *, skip_existing: bool = True) -> InitializationResult:
        """Initialize all collections defined in the manifest."""
        result = InitializationResult()

        for entity_type, config in self._manifest.collections.items():
            collection_name = self._manifest.get_collection_name(entity_type)

            try:
                should_skip = self._prepare_collection(collection_name, skip_existing=skip_existing)
            except QdrantAPIError, QdrantConnectionError:
                logger.exception("collection_preparation_failed", collection=collection_name)
                result.failed.append(collection_name)
                continue
            if should_skip:
                result.skipped.append(collection_name)
                continue

            if self._create_collection(collection_name, config):
                result.created.append(collection_name)
            else:
                result.failed.append(collection_name)

        return result

    def initialize_one(self, entity_type: str, *, skip_existing: bool = True) -> bool:
        """Initialize a single collection by entity type."""
        collection_name = self._manifest.get_collection_name(entity_type)
        config = self._manifest.get_collection_config(entity_type)

        try:
            should_skip = self._prepare_collection(collection_name, skip_existing=skip_existing)
        except QdrantAPIError, QdrantConnectionError:
            logger.exception("collection_preparation_failed", collection=collection_name)
            return False
        if should_skip:
            return True

        return self._create_collection(collection_name, config)

    def _prepare_collection(self, name: str, *, skip_existing: bool) -> bool:
        """Return whether creation should be skipped, deleting first for recreation."""
        if not self._client.collection_exists(name):
            return False
        if skip_existing:
            logger.info("collection_exists_skipping", collection=name)
            return True

        logger.info("collection_exists_deleting", collection=name)
        self._client.delete_collection(name)
        return False

    def _create_collection(self, name: str, config: CollectionConfig) -> bool:
        """Create a single collection from config."""
        payload = _build_payload(config)
        _log_collection_info(name, config)

        try:
            self._client.create_collection(name, payload)
        except QdrantAPIError, QdrantConnectionError:
            logger.exception("collection_creation_failed", collection=name)
            return False
        else:
            logger.info("collection_created", collection=name)
            return True


def _build_payload(config: CollectionConfig) -> QdrantCollectionPayload:
    """Build Qdrant REST API payload from collection config."""
    payload = QdrantCollectionPayload(
        vectors={name: defn.model_dump(exclude_none=True) for name, defn in config.qdrant.vectors.items()},
    )

    if config.qdrant.sparse:
        sparse_cfg = config.qdrant.sparse
        payload["sparse_vectors"] = {
            sparse_cfg.name: _SparseVectorEntry(
                index=_SparseIndexConfig(full_scan_threshold=sparse_cfg.full_scan_threshold),
            ),
        }

    return payload


def _log_collection_info(name: str, config: CollectionConfig) -> None:
    """Log collection creation details."""
    logger.info("creating_collection", collection=name, version=config.version)

    for vec_name, vec_def in config.qdrant.vectors.items():
        vec_type = "multi-vector" if vec_def.multivector_config else "dense"
        logger.info("vector_config", name=vec_name, size=vec_def.size, distance=vec_def.distance, type=vec_type)

    if config.qdrant.sparse:
        logger.info("sparse_vector_config", name=config.qdrant.sparse.name)

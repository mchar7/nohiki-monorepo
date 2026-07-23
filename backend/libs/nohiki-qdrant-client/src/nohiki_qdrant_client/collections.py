"""Qdrant collection management (model-agnostic)."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from qdrant_client.http import models

if TYPE_CHECKING:
    from qdrant_client.async_qdrant_client import AsyncQdrantClient
    from qdrant_client.qdrant_client import QdrantClient

logger = get_logger(__name__)

# Distance metric mapping
DISTANCE_METRICS: dict[str, models.Distance] = {
    "Dot": models.Distance.DOT,
    "Cosine": models.Distance.COSINE,
    "Euclid": models.Distance.EUCLID,
}

# Standard payload field schemas for indexing
PAYLOAD_INDEX_SCHEMAS: list[tuple[str, models.PayloadSchemaType]] = [
    ("is_active", models.PayloadSchemaType.BOOL),
    ("entity_type", models.PayloadSchemaType.KEYWORD),
    ("collection_version", models.PayloadSchemaType.KEYWORD),
    ("content_hash", models.PayloadSchemaType.KEYWORD),
    ("job_type", models.PayloadSchemaType.KEYWORD),
    ("work_arrangement", models.PayloadSchemaType.KEYWORD),
    ("posted_at", models.PayloadSchemaType.DATETIME),
    ("company", models.PayloadSchemaType.KEYWORD),
]


@dataclass(frozen=True, slots=True)
class CollectionConfig:
    """Configuration for creating a Qdrant collection."""

    collection_version: str
    entity_type: str
    muvera_dim: int
    distance_metric: str = "Dot"
    alias_name: str | None = None
    on_disk: bool = True
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100


def get_collection_name(entity_type: str, semantic_repr_id: str) -> str:
    """Generate collection name from entity type and semantic representation ID.

    Args:
        entity_type: "jobs" or "profiles"
        semantic_repr_id: e.g., "jobs.semantic_repr.v1"

    Returns:
        Collection name with sanitized semantic_repr_id

    """
    # Sanitize semantic_repr_id for Qdrant collection name
    sanitized_repr = semantic_repr_id.replace(".", "_").replace("-", "_")
    return f"{entity_type}_{sanitized_repr}"


def create_collection_from_manifest(client: QdrantClient, config: CollectionConfig) -> str:
    """Create Qdrant collection based on SemanticRepresentationManifest.

    CRITICAL: Distance metric comes from manifest. Default is DOT for MUVERA.
    No hardcoded dimensions: all from manifest config.

    Args:
        client: Qdrant client
        config: Collection configuration from manifest

    Returns:
        Collection name

    """
    collection_name = get_collection_name(config.entity_type, config.collection_version)

    # Map distance metric string to Qdrant enum
    distance = DISTANCE_METRICS.get(config.distance_metric, models.Distance.DOT)

    client.recreate_collection(
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

    # Create payload indexes
    for field, schema in PAYLOAD_INDEX_SCHEMAS:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field,
            field_schema=schema,
        )

    # Create alias if specified
    if config.alias_name:
        _create_or_update_alias(client, config.alias_name, collection_name)

    logger.info(
        "Collection created",
        collection=collection_name,
        muvera_dim=config.muvera_dim,
        distance=config.distance_metric,
        alias=config.alias_name,
    )

    return collection_name


def update_alias(
    client: QdrantClient,
    alias_name: str,
    new_collection_name: str,
) -> None:
    """Atomically update alias to point to new collection.

    Used for zero-downtime model migrations.

    Args:
        client: Qdrant client
        alias_name: Alias name to update
        new_collection_name: New collection to point to

    """
    client.update_collection_aliases(
        change_aliases_operations=[
            models.DeleteAliasOperation(
                delete_alias=models.DeleteAlias(alias_name=alias_name),
            ),
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=new_collection_name,
                    alias_name=alias_name,
                ),
            ),
        ],
    )
    logger.info("Alias updated", alias=alias_name, collection=new_collection_name)


def delete_collection(client: QdrantClient, collection_name: str) -> None:
    """Delete a Qdrant collection.

    Args:
        client: Qdrant client
        collection_name: Collection to delete

    """
    client.delete_collection(collection_name=collection_name)
    logger.info("Collection deleted", collection=collection_name)


def collection_exists(client: QdrantClient, collection_name: str) -> bool:
    """Check if a collection exists.

    Args:
        client: Qdrant client
        collection_name: Collection name to check

    Returns:
        True if collection exists

    """
    return bool(client.collection_exists(collection_name=collection_name))


def _create_or_update_alias(
    client: QdrantClient,
    alias_name: str,
    collection_name: str,
) -> None:
    """Create or update an alias (internal helper)."""
    # Try to delete existing alias first (ignore if not exists)
    with contextlib.suppress(Exception):
        client.update_collection_aliases(
            change_aliases_operations=[
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=alias_name),
                ),
            ],
        )

    client.update_collection_aliases(
        change_aliases_operations=[
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=collection_name,
                    alias_name=alias_name,
                ),
            ),
        ],
    )
    logger.info("Alias created", alias=alias_name, collection=collection_name)


async def _create_or_update_alias_async(
    client: AsyncQdrantClient,
    alias_name: str,
    collection_name: str,
) -> None:
    """Create or update an alias (async internal helper)."""
    # Try to delete existing alias first (ignore if not exists)
    with contextlib.suppress(Exception):
        await client.update_collection_aliases(
            change_aliases_operations=[
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=alias_name),
                ),
            ],
        )

    await client.update_collection_aliases(
        change_aliases_operations=[
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=collection_name,
                    alias_name=alias_name,
                ),
            ),
        ],
    )
    logger.info("Alias created (async)", alias=alias_name, collection=collection_name)

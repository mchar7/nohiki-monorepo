"""Batch embedding helpers for skill triple-embedding via EmbeddingPublisher."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import NAMESPACE_DNS, UUID, uuid5

from nohiki.ml.v1 import BatchEmbeddingItem, EntityType
from nohiki_common_exceptions import DataIntegrityError
from nohiki_qdrant_client import UpsertPayload, VectorPoint

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nohiki_embedding_client import BatchEmbeddingItemResult


_BATCH_ITEM_MAX_ALT_LABELS: Final[int] = 10
_CONTEXT_KEY_VARIANT: Final[str] = "variant"
_CONTEXT_KEY_SKILL_ID: Final[str] = "skill_id"
_CONTEXT_KEY_NAME: Final[str] = "name"
_CONTEXT_KEY_OCCUPATION_CODE: Final[str] = "occupation_code"
_CONTEXT_KEY_OCCUPATION_LABEL: Final[str] = "occupation_label"
_ENTITY_TYPE_SKILL: Final[str] = EntityType.SKILL.name.lower()
_ENTITY_TYPE_OCCUPATION: Final[str] = EntityType.OCCUPATION.name.lower()

# Base namespace for deriving entity-specific embedding namespaces (UUID5)
# RFC 4122 compliant: derived from DNS namespace for deterministic reproducibility
_BASE_EMBEDDING_NAMESPACE: Final[UUID] = uuid5(NAMESPACE_DNS, "nohiki.skill-graph.embeddings")


def _get_entity_namespace(entity_type: EntityType) -> UUID:
    """Derive deterministic namespace UUID for an entity type.

    Args:
        entity_type: The entity type to get namespace for.

    Returns:
        UUID5 derived from base namespace and entity type name.

    """
    return uuid5(_BASE_EMBEDDING_NAMESPACE, entity_type.name)


# Pre-computed namespaces for hot-path performance
_SKILL_EMBEDDING_NAMESPACE: Final[UUID] = _get_entity_namespace(EntityType.SKILL)
_OCCUPATION_EMBEDDING_NAMESPACE: Final[UUID] = _get_entity_namespace(EntityType.OCCUPATION)


class EmbeddingVariant(StrEnum):
    """Embedding source variant for triple-embedding strategy."""

    LABEL = "label"
    DESCRIPTION = "description"
    ALT_LABELS = "alt_labels"


def skill_variant_point_id(skill_id: UUID, variant: EmbeddingVariant) -> str:
    """Generate deterministic UUID for a skill embedding variant.

    Uses UUID5 with a fixed namespace to produce consistent point IDs
    from the skill_id and variant combination. This ensures Qdrant
    receives valid UUIDs while maintaining deterministic mapping.

    Args:
        skill_id: Canonical skill UUID.
        variant: Embedding variant (label, description, alt_labels).

    Returns:
        String representation of UUID5 for this skill+variant.

    """
    compound_key = f"{skill_id}_{variant}"
    return str(uuid5(_SKILL_EMBEDDING_NAMESPACE, compound_key))


def build_skill_batch_items(
    skill_id: UUID,
    preferred_label: str,
    description: str | None,
    alt_labels: Sequence[str],
) -> list[BatchEmbeddingItem]:
    """Build the 3-item batch for triple embedding of a skill.

    Creates one BatchEmbeddingItem per embedding variant (label,
    description, alt_labels). Point IDs are deterministic UUIDs
    generated via UUID5 from the skill_id and variant.

    Args:
        skill_id: Canonical skill UUID.
        preferred_label: Canonical skill name used for LABEL variant.
        description: Skill description for DESCRIPTION variant.
            Falls back to preferred_label if None.
        alt_labels: Alternative labels joined for ALT_LABELS variant.
            Falls back to preferred_label if empty.

    Returns:
        List of exactly 3 BatchEmbeddingItem messages.

    """
    skill_id_str = str(skill_id)
    alt_text = ", ".join(alt_labels[:_BATCH_ITEM_MAX_ALT_LABELS]) if alt_labels else preferred_label
    desc_text = description or preferred_label

    def _item(variant: EmbeddingVariant, text: str) -> BatchEmbeddingItem:
        return BatchEmbeddingItem(
            point_id=skill_variant_point_id(skill_id, variant),
            entity_id=skill_id_str,
            text=text,
            item_attributes={
                _CONTEXT_KEY_VARIANT: variant,
                _CONTEXT_KEY_SKILL_ID: skill_id_str,
                _CONTEXT_KEY_NAME: preferred_label,
            },
        )

    return [
        _item(EmbeddingVariant.LABEL, preferred_label),
        _item(EmbeddingVariant.DESCRIPTION, desc_text),
        _item(EmbeddingVariant.ALT_LABELS, alt_text),
    ]


def _collection_version_for_result(result: BatchEmbeddingItemResult) -> str:
    """Require a non-empty, consistent collection version before a Qdrant write."""
    versions = {embedding.collection_version for embedding in result.embeddings}
    if len(versions) != 1 or not (collection_version := next(iter(versions), "")):
        raise DataIntegrityError(
            resource_type="EmbeddingVector",
            resource_ids=(result.point_id,),
            message=f"Point {result.point_id} has missing or inconsistent collection versions",
        )
    return collection_version


def build_skill_vector_points(
    results: list[BatchEmbeddingItemResult],
) -> list[VectorPoint]:
    """Convert batch embedding results to Qdrant VectorPoints.

    Each BatchEmbeddingItemResult maps to one VectorPoint. The payload
    includes entity_id, entity_type, collection_version, content_hash,
    and embedding_source variant from the request context.

    Args:
        results: List of BatchEmbeddingItemResult from the batch embedding callback.

    Returns:
        List of VectorPoint ready for upsert_vector_points_batch.

    """
    points: list[VectorPoint] = []
    for result in results:
        collection_version = _collection_version_for_result(result)
        payload = UpsertPayload(
            entity_id=result.entity_id,
            entity_type=_ENTITY_TYPE_SKILL,
            collection_version=collection_version,
            content_hash=result.content_hash,
            extra={
                "skill_id": result.entity_id,
                "name": result.item_attributes.get(_CONTEXT_KEY_NAME, ""),
                "embedding_source": result.item_attributes.get(_CONTEXT_KEY_VARIANT, ""),
            },
        )
        points.append(
            VectorPoint(
                point_id=result.point_id,
                embeddings=list(result.embeddings),
                payload=payload,
            )
        )
    return points


def occupation_point_id(occupation_code: str) -> str:
    """Generate deterministic UUID for an occupation embedding.

    Uses UUID5 with a fixed namespace to produce consistent point IDs
    from the occupation code. This ensures Qdrant receives valid UUIDs
    while maintaining deterministic mapping.

    Args:
        occupation_code: ESCO occupation code (e.g., "2654.1.7").

    Returns:
        String representation of UUID5 for this occupation.

    """
    return str(uuid5(_OCCUPATION_EMBEDDING_NAMESPACE, occupation_code))


def build_occupation_batch_item(
    occupation_code: str,
    preferred_label: str,
) -> BatchEmbeddingItem:
    """Build a single BatchEmbeddingItem for occupation label embedding.

    Uses label-only embedding strategy per approved design. Description
    is stored in OccupationNode table for future A/B testing but not
    embedded initially.

    Args:
        occupation_code: ESCO occupation code (e.g., "2654.1.7").
        preferred_label: Canonical occupation name to embed.

    Returns:
        Single BatchEmbeddingItem for this occupation.

    """
    return BatchEmbeddingItem(
        point_id=occupation_point_id(occupation_code),
        entity_id=occupation_code,
        text=preferred_label,
        item_attributes={
            _CONTEXT_KEY_OCCUPATION_CODE: occupation_code,
            _CONTEXT_KEY_OCCUPATION_LABEL: preferred_label,
        },
    )


def build_occupation_vector_points(
    results: list[BatchEmbeddingItemResult],
) -> list[VectorPoint]:
    """Convert batch embedding results to Qdrant VectorPoints for occupations.

    Each BatchEmbeddingItemResult maps to one VectorPoint. The payload
    includes occupation_code, occupation_label, entity_type, collection_version,
    and content_hash.

    Args:
        results: List of BatchEmbeddingItemResult from the batch embedding callback.

    Returns:
        List of VectorPoint ready for upsert_vector_points_batch.

    """
    points: list[VectorPoint] = []
    for result in results:
        collection_version = _collection_version_for_result(result)
        payload = UpsertPayload(
            entity_id=result.entity_id,
            entity_type=_ENTITY_TYPE_OCCUPATION,
            collection_version=collection_version,
            content_hash=result.content_hash,
            extra={
                "occupation_code": result.entity_id,
                "occupation_label": result.item_attributes.get(_CONTEXT_KEY_OCCUPATION_LABEL, ""),
            },
        )
        points.append(
            VectorPoint(
                point_id=result.point_id,
                embeddings=list(result.embeddings),
                payload=payload,
            )
        )
    return points

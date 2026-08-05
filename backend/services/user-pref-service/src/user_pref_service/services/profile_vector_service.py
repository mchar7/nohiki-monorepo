"""Manifest-schema Qdrant lifecycle for canonical search profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.ml.v1 import EmbeddingType, EmbeddingVector, EntityType
from nohiki_qdrant_client import UpsertPayload, VectorPoint

from user_pref_service.core.config import get_manifest, get_profiles_collection_name, get_qdrant_client

if TYPE_CHECKING:
    from collections.abc import Sequence

    from user_pref_service.db.models import SearchPref

_REQUIRED_RETRIEVAL_TYPES = (EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT)


def build_profile_vector_point(profile: SearchPref) -> VectorPoint | None:
    """Build a deterministic profile point from persisted owned state."""
    if not profile.query_artifacts_data or not profile.semantic_content_hash:
        return None

    by_type: dict[EmbeddingType, EmbeddingVector] = {}
    for data in profile.query_artifacts_data:
        embedding = EmbeddingVector.from_dict(data)
        by_type[embedding.embedding_type] = embedding
    if any(kind not in by_type for kind in _REQUIRED_RETRIEVAL_TYPES):
        return None

    collection_version = get_manifest().get_entity_version(EntityType.PROFILE)
    return VectorPoint(
        point_id=str(profile.id),
        embeddings=[by_type[kind] for kind in _REQUIRED_RETRIEVAL_TYPES],
        payload=UpsertPayload(
            entity_id=str(profile.id),
            entity_type="profile",
            collection_version=collection_version,
            content_hash=profile.semantic_content_hash,
            is_active=profile.is_active,
            extra={
                "user_id": str(profile.user_id),
                "pref_id": str(profile.id),
                "pref_name": profile.pref_name,
            },
        ),
    )


async def upsert_profile_point(profile: SearchPref) -> None:
    """Upsert persisted searchable state, waiting for Qdrant acknowledgement."""
    if point := build_profile_vector_point(profile):
        await get_qdrant_client().upsert_vector_points_batch(
            get_profiles_collection_name(),
            [point],
        )


async def delete_profile_points(pref_ids: Sequence[UUID]) -> None:
    """Delete canonical profile points in one acknowledged request."""
    if pref_ids:
        await get_qdrant_client().delete_points(
            get_profiles_collection_name(),
            [str(pref_id) for pref_id in pref_ids],
        )

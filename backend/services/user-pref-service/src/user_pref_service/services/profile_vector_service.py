"""Manifest-schema Qdrant lifecycle for canonical search profiles."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.ml.v1 import EmbeddingResult, EmbeddingType, EntityType
from nohiki_common_exceptions import ValidationError
from nohiki_qdrant_client import UpsertPayload, VectorPoint

from user_pref_service.core.config import get_manifest, get_profiles_collection_name, get_qdrant_client

if TYPE_CHECKING:
    from collections.abc import Sequence

    from user_pref_service.db.models import SearchPref

_REQUIRED_RETRIEVAL_TYPES = (EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT)


def build_profile_vector_point(
    profile: SearchPref,
    result: EmbeddingResult,
    *,
    embedded_text: str,
) -> VectorPoint:
    """Build a complete, deterministic profile point from callback artifacts."""
    by_type = {embedding.embedding_type: embedding for embedding in result.embeddings}
    missing = set(_REQUIRED_RETRIEVAL_TYPES).difference(by_type)
    if missing:
        names = ", ".join(sorted(kind.name for kind in missing))
        msg = f"Profile embedding result is incomplete: missing {names}"
        raise ValidationError(msg)

    content_hash = result.content_hash or sha256(embedded_text.encode()).hexdigest()
    collection_version = get_manifest().get_entity_version(EntityType.PROFILE)
    return VectorPoint(
        point_id=str(profile.id),
        embeddings=[by_type[kind] for kind in _REQUIRED_RETRIEVAL_TYPES],
        payload=UpsertPayload(
            entity_id=str(profile.id),
            entity_type="profile",
            collection_version=collection_version,
            content_hash=content_hash,
            is_active=profile.is_active,
            extra={
                "user_id": str(profile.user_id),
                "pref_id": str(profile.id),
                "pref_name": profile.pref_name,
            },
        ),
    )


async def upsert_profile_point(profile: SearchPref, result: EmbeddingResult, *, embedded_text: str) -> None:
    """Replace the canonical UUID point, waiting for Qdrant acknowledgement."""
    await get_qdrant_client().upsert_vector_points_batch(
        get_profiles_collection_name(),
        [build_profile_vector_point(profile, result, embedded_text=embedded_text)],
    )


async def delete_profile_points(pref_ids: Sequence[UUID]) -> None:
    """Delete canonical profile points in one acknowledged request."""
    if pref_ids:
        await get_qdrant_client().delete_points(
            get_profiles_collection_name(),
            [str(pref_id) for pref_id in pref_ids],
        )

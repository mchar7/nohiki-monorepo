"""Profile Qdrant point mapping and transport lifecycle contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, MultiVectorData, SparseData
from user_pref_service.services.profile_vector_service import (
    build_profile_vector_point,
    delete_profile_points,
    upsert_profile_point,
)


def _retrieval_vectors() -> list[EmbeddingVector]:
    return [
        EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=[0.1, 0.2], num_tokens=1, token_dim=2),
        ),
        EmbeddingVector(embedding_type=EmbeddingType.SPARSE, sparse=SparseData(indices=[3], values=[0.7])),
        EmbeddingVector(embedding_type=EmbeddingType.MUVERA, dense=DenseData(values=[0.4, 0.5])),
    ]


def _profile() -> MagicMock:
    profile = MagicMock()
    profile.id = uuid4()
    profile.user_id = uuid4()
    profile.pref_name = "Platform roles"
    profile.is_active = True
    profile.collection_version = "stale-version"
    profile.query_artifacts_data = [vector.to_dict() for vector in _retrieval_vectors()]
    profile.semantic_content_hash = "b" * 64
    return profile


def test_build_point_reconstructs_persisted_vectors_and_uses_manifest_version() -> None:
    profile = _profile()

    point = build_profile_vector_point(profile)

    assert point is not None
    assert point.point_id == str(profile.id)
    assert [vector.embedding_type for vector in point.embeddings] == [
        EmbeddingType.MUVERA,
        EmbeddingType.SPARSE,
        EmbeddingType.COLBERT,
    ]
    assert point.payload.entity_id == str(profile.id)
    assert point.payload.entity_type == "profile"
    assert point.payload.collection_version == "v2"
    assert point.payload.content_hash == "b" * 64
    assert point.payload.is_active is True
    assert point.payload.extra == {
        "user_id": str(profile.user_id),
        "pref_id": str(profile.id),
        "pref_name": "Platform roles",
    }


@pytest.mark.parametrize("missing", ["vectors", "hash"])
def test_incomplete_persisted_search_state_does_not_build_a_point(missing: str) -> None:
    profile = _profile()
    if missing == "vectors":
        profile.query_artifacts_data = [
            vector.to_dict() for vector in _retrieval_vectors() if vector.embedding_type != EmbeddingType.COLBERT
        ]
    else:
        profile.semantic_content_hash = None

    assert build_profile_vector_point(profile) is None


@pytest.mark.asyncio
async def test_incomplete_persisted_state_leaves_existing_point_unchanged() -> None:
    profile = _profile()
    profile.query_artifacts_data = None
    client = AsyncMock()

    with patch("user_pref_service.services.profile_vector_service.get_qdrant_client", return_value=client):
        await upsert_profile_point(profile)

    client.upsert_vector_points_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_upserts_same_canonical_uuid_without_duplicate_identity() -> None:
    profile = _profile()
    client = AsyncMock()
    with (
        patch("user_pref_service.services.profile_vector_service.get_qdrant_client", return_value=client),
        patch(
            "user_pref_service.services.profile_vector_service.get_profiles_collection_name", return_value="profiles_v2"
        ),
    ):
        await upsert_profile_point(profile)
        await upsert_profile_point(profile)

    assert client.upsert_vector_points_batch.await_count == 2
    first = client.upsert_vector_points_batch.await_args_list[0].args
    second = client.upsert_vector_points_batch.await_args_list[1].args
    assert first[0] == second[0] == "profiles_v2"
    assert first[1][0].point_id == second[1][0].point_id == str(profile.id)


@pytest.mark.asyncio
async def test_bulk_delete_uses_canonical_ids_and_empty_is_transport_noop() -> None:
    ids = [uuid4(), uuid4()]
    client = AsyncMock()
    with (
        patch("user_pref_service.services.profile_vector_service.get_qdrant_client", return_value=client),
        patch(
            "user_pref_service.services.profile_vector_service.get_profiles_collection_name", return_value="profiles_v2"
        ),
    ):
        await delete_profile_points(ids)
        await delete_profile_points([])

    client.delete_points.assert_awaited_once_with("profiles_v2", [str(value) for value in ids])

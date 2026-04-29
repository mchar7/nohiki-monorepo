"""Profile Qdrant point mapping and transport lifecycle contracts."""

from __future__ import annotations

from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.ml.v1 import (
    DenseData,
    EmbeddingResult,
    EmbeddingType,
    EmbeddingVector,
    MultiVectorData,
    SparseData,
)
from nohiki_common_exceptions import ValidationError
from user_pref_service.services.profile_vector_service import (
    build_profile_vector_point,
    delete_profile_points,
    upsert_profile_point,
)


def _result(*, content_hash: str = "") -> EmbeddingResult:
    return EmbeddingResult(
        embeddings=[
            EmbeddingVector(
                embedding_type=EmbeddingType.COLBERT,
                multi_vector=MultiVectorData(values=[0.1, 0.2], num_tokens=1, token_dim=2),
            ),
            EmbeddingVector(embedding_type=EmbeddingType.SPARSE, sparse=SparseData(indices=[3], values=[0.7])),
            EmbeddingVector(embedding_type=EmbeddingType.MUVERA, dense=DenseData(values=[0.4, 0.5])),
        ],
        collection_version="v1",
        content_hash=content_hash,
    )


def _profile() -> MagicMock:
    profile = MagicMock()
    profile.id = uuid4()
    profile.user_id = uuid4()
    profile.pref_name = "Platform roles"
    profile.is_active = True
    profile.collection_version = "stale-version"
    return profile


def test_build_point_maps_three_vectors_and_stales_callback_version() -> None:
    profile = _profile()
    result = _result()
    embedded_text = "Python Rust distributed systems"

    point = build_profile_vector_point(profile, result, embedded_text=embedded_text)

    assert point.point_id == str(profile.id)
    assert [vector.embedding_type for vector in point.embeddings] == [
        EmbeddingType.MUVERA,
        EmbeddingType.SPARSE,
        EmbeddingType.COLBERT,
    ]
    assert point.payload.entity_id == str(profile.id)
    assert point.payload.entity_type == "profile"
    assert point.payload.collection_version == "v2"
    assert point.payload.content_hash == sha256(embedded_text.encode()).hexdigest()
    assert point.payload.is_active is True
    assert point.payload.extra == {
        "user_id": str(profile.user_id),
        "pref_id": str(profile.id),
        "pref_name": "Platform roles",
    }


def test_callback_result_content_hash_is_authoritative() -> None:
    point = build_profile_vector_point(_profile(), _result(content_hash="b" * 64), embedded_text="exact text")
    assert point.payload.content_hash == "b" * 64


def test_incomplete_result_is_rejected_without_weakening_mapping() -> None:
    result = _result()
    result.embeddings = [vector for vector in result.embeddings if vector.embedding_type != EmbeddingType.COLBERT]
    with pytest.raises(ValidationError, match="missing COLBERT"):
        build_profile_vector_point(_profile(), result, embedded_text="text")


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
        await upsert_profile_point(profile, _result(), embedded_text="same text")
        await upsert_profile_point(profile, _result(), embedded_text="same text")

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

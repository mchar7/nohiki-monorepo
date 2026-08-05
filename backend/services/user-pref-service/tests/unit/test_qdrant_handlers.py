"""Committed preference fact to Qdrant projection contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, MultiVectorData, SparseData
from nohiki.user.pref.v1 import PrefCreated, PrefDeleted, PrefUpdated
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from user_pref_service.events.qdrant_handlers import (
    handle_pref_created,
    handle_pref_deleted,
    handle_pref_updated,
)


def _context() -> MessageContext:
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=create_mock_session(),
    )


def _searchable_profile() -> MagicMock:
    profile = MagicMock()
    profile.id = uuid4()
    profile.user_id = uuid4()
    profile.pref_name = "Persisted profile"
    profile.is_active = True
    profile.enrichment_terminal_status = None
    profile.semantic_content_hash = "a" * 64
    profile.semantic_content_generation = 1
    profile.collection_version = "v2"
    profile.query_artifacts_data = [
        EmbeddingVector(embedding_type=EmbeddingType.MUVERA, dense=DenseData(values=[0.1])).to_dict(),
        EmbeddingVector(
            embedding_type=EmbeddingType.SPARSE,
            sparse=SparseData(indices=[1], values=[0.2]),
        ).to_dict(),
        EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=[0.3, 0.4], num_tokens=1, token_dim=2),
        ).to_dict(),
    ]
    return profile


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "message_type"),
    [(handle_pref_created, PrefCreated), (handle_pref_updated, PrefUpdated)],
)
async def test_committed_lifecycle_handler_loads_owned_state_and_only_then_upserts(
    handler: object,
    message_type: type[PrefCreated | PrefUpdated],
) -> None:
    pref_id = uuid4()
    profile = _searchable_profile()
    message = message_type(pref_id=str(pref_id), user_id=str(uuid4()))
    profile_from_event = MagicMock(
        semantic_content_generation=1,
        semantic_content_hash=profile.semantic_content_hash,
        collection_version=profile.collection_version,
    )
    message.pref_snapshot = profile_from_event
    order: list[str] = []

    with (
        patch(
            "user_pref_service.events.qdrant_handlers.profile_service.get_profile_by_id_optional",
            new_callable=AsyncMock,
            side_effect=lambda *_args: (order.append("load"), profile)[1],
        ) as load,
        patch(
            "user_pref_service.events.qdrant_handlers.upsert_profile_point",
            side_effect=lambda *_args: order.append("upsert"),
        ) as upsert,
    ):
        assert order == []
        await cast(Callable[[PrefCreated | PrefUpdated, MessageContext], Awaitable[None]], handler)(
            message,
            _context(),
        )

    assert order == ["load", "upsert"]
    load.assert_awaited_once()
    assert load.await_args is not None
    assert load.await_args.args[1] == pref_id
    upsert.assert_awaited_once_with(profile)
    assert upsert.await_args is not None
    assert upsert.await_args.args[0] is not profile_from_event


@pytest.mark.asyncio
async def test_delayed_generation_fact_cannot_project_newer_pending_profile_state() -> None:
    profile = _searchable_profile()
    profile.semantic_content_generation = 2
    profile.semantic_content_hash = "b" * 64
    profile.query_artifacts_data = [
        EmbeddingVector(
            embedding_type=EmbeddingType.MUVERA,
            dense=DenseData(values=[0.1]),
            content_hash="a" * 64,
            collection_version="v2",
        ).to_dict(),
        EmbeddingVector(
            embedding_type=EmbeddingType.SPARSE,
            sparse=SparseData(indices=[1], values=[0.2]),
            content_hash="a" * 64,
            collection_version="v2",
        ).to_dict(),
        EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=[0.3, 0.4], num_tokens=1, token_dim=2),
            content_hash="a" * 64,
            collection_version="v2",
        ).to_dict(),
    ]
    message = PrefUpdated(pref_id=str(profile.id), user_id=str(profile.user_id))
    message.pref_snapshot = MagicMock(
        semantic_content_generation=1,
        semantic_content_hash="a" * 64,
        collection_version="v2",
    )

    with (
        patch(
            "user_pref_service.events.qdrant_handlers.profile_service.get_profile_by_id_optional",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "user_pref_service.events.qdrant_handlers.upsert_profile_point",
            new_callable=AsyncMock,
        ) as upsert,
    ):
        await handle_pref_updated(message, _context())

    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_qdrant_write_failure_raises_from_committed_handler() -> None:
    profile = _searchable_profile()
    client = AsyncMock()
    client.upsert_vector_points_batch.side_effect = RuntimeError("qdrant unavailable")
    message = PrefUpdated(pref_id=str(profile.id), user_id=str(profile.user_id))
    message.pref_snapshot = MagicMock(
        semantic_content_generation=profile.semantic_content_generation,
        semantic_content_hash=profile.semantic_content_hash,
        collection_version=profile.collection_version,
    )

    with (
        patch(
            "user_pref_service.events.qdrant_handlers.profile_service.get_profile_by_id_optional",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch("user_pref_service.services.profile_vector_service.get_qdrant_client", return_value=client),
        pytest.raises(RuntimeError, match="qdrant unavailable"),
    ):
        await handle_pref_updated(message, _context())

    client.upsert_vector_points_batch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [None, MagicMock(is_active=False)])
async def test_missing_or_inactive_current_profile_deletes_stable_point(profile: MagicMock | None) -> None:
    pref_id = uuid4()
    with (
        patch(
            "user_pref_service.events.qdrant_handlers.profile_service.get_profile_by_id_optional",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "user_pref_service.events.qdrant_handlers.delete_profile_points",
            new_callable=AsyncMock,
        ) as delete,
        patch(
            "user_pref_service.events.qdrant_handlers.upsert_profile_point",
            new_callable=AsyncMock,
        ) as upsert,
    ):
        await handle_pref_updated(PrefUpdated(pref_id=str(pref_id), user_id=str(uuid4())), _context())

    delete.assert_awaited_once_with([pref_id])
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_enrichment_failure_leaves_existing_point_unchanged() -> None:
    profile = _searchable_profile()
    profile.enrichment_terminal_status = "failed"
    with (
        patch(
            "user_pref_service.events.qdrant_handlers.profile_service.get_profile_by_id_optional",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "user_pref_service.events.qdrant_handlers.delete_profile_points",
            new_callable=AsyncMock,
        ) as delete,
        patch(
            "user_pref_service.events.qdrant_handlers.upsert_profile_point",
            new_callable=AsyncMock,
        ) as upsert,
    ):
        await handle_pref_updated(
            PrefUpdated(pref_id=str(profile.id), user_id=str(profile.user_id)),
            _context(),
        )

    delete.assert_not_awaited()
    upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_deleted_fact_uses_stable_pref_id_and_awaits_delete() -> None:
    pref_id = uuid4()
    with patch(
        "user_pref_service.events.qdrant_handlers.delete_profile_points",
        new_callable=AsyncMock,
    ) as delete:
        await handle_pref_deleted(
            PrefDeleted(pref_id=str(pref_id), user_id=str(uuid4())),
            _context(),
        )

    delete.assert_awaited_once_with([UUID(str(pref_id))])

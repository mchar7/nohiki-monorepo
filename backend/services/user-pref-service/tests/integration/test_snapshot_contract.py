"""End-to-end contract coverage for canonical empty preference updates."""

from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
from nohiki.common.v1 import CallbackHeader, WorkArrangement
from nohiki.ml.v1 import (
    DenseData,
    EmbeddingCallback,
    EmbeddingRequested,
    EmbeddingResult,
    EmbeddingType,
    EmbeddingVector,
    EncodingMode,
    EntityType,
    MultiVectorData,
    SparseData,
)
from nohiki.user.pref.v1 import PrefUpdated, PrefUpdateRequested
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import MessageContext
from user_pref_service.core.config import get_manifest
from user_pref_service.db.models import SearchPref
from user_pref_service.events.callbacks import handle_embedding_callback
from user_pref_service.events.commands import handle_pref_update_requested

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession


class _CapturingOutbox:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.event: PrefUpdated | None = None

    async def write_event(self, *, db: object, params: object, event: object) -> UUID:
        del db, params
        self.events.append(event)
        if isinstance(event, PrefUpdated):
            self.event = event
        return uuid4()


@pytest.mark.integration
@pytest.mark.requires_docker
@pytest.mark.asyncio
async def test_empty_update_emits_snapshot_through_real_embedding_callback(
    async_session: AsyncSession,
    setup_database_schema: None,
) -> None:
    """The update and real callback preserve canonical empty repeated values."""
    _ = setup_database_schema
    user_id = uuid4()
    profile = SearchPref(
        id=uuid4(),
        user_id=user_id,
        pref_name="Empty update profile",
        search_keywords=["python"],
        work_arrangements=[WorkArrangement.REMOTE],
    )
    async_session.add(profile)
    await async_session.flush()

    outbox = _CapturingOutbox()
    context = MessageContext(
        topic="user-pref.cmd.update-requested.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=async_session,
        outbox=cast("OutboxWriter", outbox),
    )
    request_id = str(uuid4())
    command = PrefUpdateRequested(
        metadata=create_event_metadata("user-pref-service-test", request_id),
        request_id=request_id,
        user_id=str(user_id),
        pref_id=str(profile.id),
        updated_fields=["search_keywords", "work_arrangements"],
    )

    await handle_pref_update_requested(command, context)
    embedding_request = outbox.events[0]
    assert isinstance(embedding_request, EmbeddingRequested)

    callback = EmbeddingCallback(
        metadata=create_event_metadata("ml-compute-service-test"),
        callback=CallbackHeader(
            operation_id=embedding_request.command.operation_id,
            caller_context=embedding_request.command.caller_context,
        ),
        entity_id=str(profile.id),
        entity_type=EntityType.PROFILE,
        success=EmbeddingResult(
            collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
            content_hash=profile.semantic_content_hash or "",
            requested_types=[
                EmbeddingType.MUVERA,
                EmbeddingType.SPARSE,
                EmbeddingType.COLBERT,
            ],
            encoding_mode=EncodingMode.QUERY,
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.MUVERA,
                    dense=DenseData(values=[0.1]),
                    content_hash=profile.semantic_content_hash or "",
                    collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
                ),
                EmbeddingVector(
                    embedding_type=EmbeddingType.SPARSE,
                    sparse=SparseData(indices=[1], values=[0.2]),
                    content_hash=profile.semantic_content_hash or "",
                    collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
                ),
                EmbeddingVector(
                    embedding_type=EmbeddingType.COLBERT,
                    multi_vector=MultiVectorData(values=[0.3], num_tokens=1, token_dim=1),
                    content_hash=profile.semantic_content_hash or "",
                    collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
                ),
            ],
        ),
    )

    await handle_embedding_callback(callback, context)

    assert outbox.event is not None
    snapshot = outbox.event.pref_snapshot
    assert snapshot.search_keywords == []
    assert snapshot.work_arrangements == []
    assert len(snapshot.query_retrieval_embeddings) == 3
    assert {embedding.embedding_type for embedding in snapshot.query_retrieval_embeddings} == {
        EmbeddingType.MUVERA,
        EmbeddingType.SPARSE,
        EmbeddingType.COLBERT,
    }
    assert all(
        embedding.collection_version == get_manifest().get_entity_version(EntityType.PROFILE)
        for embedding in snapshot.query_retrieval_embeddings
    )
    assert all(
        embedding.content_hash == profile.semantic_content_hash for embedding in snapshot.query_retrieval_embeddings
    )

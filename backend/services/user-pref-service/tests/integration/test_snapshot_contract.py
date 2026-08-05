"""End-to-end contract coverage for canonical empty preference updates."""

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from nohiki.common.v1 import CallbackHeader, WorkArrangement
from nohiki.ml.v1 import (
    DenseData,
    EmbeddingCallback,
    EmbeddingResult,
    EmbeddingType,
    EmbeddingVector,
    EncodingMode,
    EntityType,
)
from nohiki.user.pref.v1 import PrefUpdated, PrefUpdateRequested
from nohiki_db_utils import create_event_metadata
from nohiki_kafka_client import CommandContext, MessageContext
from user_pref_service.core.config import get_manifest
from user_pref_service.db.models import SearchPref
from user_pref_service.events.callbacks import handle_embedding_callback
from user_pref_service.events.commands import handle_pref_update_requested

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession


class _CapturingEmbeddingPublisher:
    def __init__(self) -> None:
        self.caller_context = b""
        self.text = ""
        self.operation_id = str(uuid4())

    async def request_embedding(
        self,
        *,
        text: str,
        entity_id: str,
        entity_type: EntityType,
        spec: object,
        context: CommandContext,
    ) -> str:
        del entity_id, entity_type, spec
        self.text = text
        self.caller_context = context.caller_context
        return self.operation_id


class _CapturingOutbox:
    def __init__(self) -> None:
        self.event: PrefUpdated | None = None

    async def write_event(self, *, db: object, params: object, event: PrefUpdated) -> UUID:
        del db, params
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
    embedding_publisher = _CapturingEmbeddingPublisher()
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

    with patch(
        "user_pref_service.events.commands.get_embedding_publisher",
        return_value=embedding_publisher,
    ):
        await handle_pref_update_requested(command, context)

    callback = EmbeddingCallback(
        metadata=create_event_metadata("ml-compute-service-test"),
        callback=CallbackHeader(
            operation_id=embedding_publisher.operation_id,
            caller_context=embedding_publisher.caller_context,
        ),
        entity_id=str(profile.id),
        entity_type=EntityType.PROFILE,
        success=EmbeddingResult(
            collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
            content_hash=profile.semantic_content_hash or "",
            requested_types=[EmbeddingType.DENSE],
            encoding_mode=EncodingMode.QUERY,
            embeddings=[
                EmbeddingVector(
                    embedding_type=EmbeddingType.DENSE,
                    dense=DenseData(values=[0.1]),
                    content_hash=profile.semantic_content_hash or "",
                    collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
                )
            ],
        ),
    )

    with patch(
        "user_pref_service.events.callbacks.upsert_profile_point",
        new_callable=AsyncMock,
    ):
        await handle_embedding_callback(callback, context)

    assert outbox.event is not None
    snapshot = outbox.event.pref_snapshot
    assert snapshot.search_keywords == []
    assert snapshot.work_arrangements == []
    assert snapshot.query_embedding is not None
    assert snapshot.query_embedding.content_hash == profile.semantic_content_hash

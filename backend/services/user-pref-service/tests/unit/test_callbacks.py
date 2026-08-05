"""Tests for durable preference enrichment callback classification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.ml.v1 import EntityType
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_db_utils import SagaStatus
from nohiki_kafka_client import MessageContext
from user_pref_service.core.config import get_manifest
from user_pref_service.core.embedding import PrefEnrichmentSagaContext
from user_pref_service.events.callbacks import (
    handle_embedding_callback,
    handle_skill_normalization_callback,
)


def _context() -> MessageContext:
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=MagicMock(),
        outbox=MagicMock(),
    )


def _saga(*, status: SagaStatus = SagaStatus.PENDING, step: str = "embedding") -> MagicMock:
    saga = MagicMock()
    saga.id = uuid4()
    saga.pref_id = uuid4()
    saga.user_id = uuid4()
    saga.request_id = uuid4()
    saga.status = status
    saga.last_dispatch_ids = {step: "op-current"}
    saga.skills_persisted = False
    saga.embedding_persisted = False
    saga.semantic_generation = 3
    saga.semantic_hash = "active-hash"
    return saga


def _message(saga_id: str, *, error: MagicMock | None = None) -> MagicMock:
    message = MagicMock()
    message.callback.caller_context = PrefEnrichmentSagaContext(saga_id=saga_id).to_bytes()
    message.callback.operation_id = "op-current"
    message.error = error
    message.success = None
    return message


@pytest.mark.asyncio
@pytest.mark.parametrize("retryability", [1, 0])
async def test_embedding_declared_error_is_classified(retryability: int) -> None:
    saga = _saga()
    retryable = bool(retryability)
    error = MagicMock(error_code="EMBEDDING_DOWN", error_message="lane unavailable", retryable=retryable)
    message = _message(str(saga.id), error=error)
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.load_saga_for_update",
            new_callable=AsyncMock,
            return_value=saga,
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.record_retryable_error",
            new_callable=AsyncMock,
        ) as record_retry,
        patch(
            "user_pref_service.events.callbacks.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
    ):
        await handle_embedding_callback(message, context)

    if retryable:
        record_retry.assert_awaited_once()
        terminate.assert_not_awaited()
    else:
        record_retry.assert_not_awaited()
        terminate.assert_awaited_once()
        termination = terminate.await_args.args[3]
        assert termination.status == SagaStatus.FAILED
        assert termination.reason == PrefEnrichmentFailedFailureReason.EMBEDDING_FAILED


@pytest.mark.asyncio
async def test_skill_terminal_error_uses_skill_failure_reason() -> None:
    saga = _saga(step="skill")
    message = _message(
        str(saga.id),
        error=MagicMock(error_code="INVALID_SKILL", error_message="invalid", retryable=False),
    )
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.load_saga_for_update",
            new_callable=AsyncMock,
            return_value=saga,
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
    ):
        await handle_skill_normalization_callback(message, context)

    assert terminate.await_args.args[3].reason == PrefEnrichmentFailedFailureReason.SKILL_NORMALIZATION_FAILED


@pytest.mark.asyncio
async def test_cancelled_saga_makes_late_callback_a_noop() -> None:
    saga = _saga(status=SagaStatus.CANCELLED)
    message = _message(str(saga.id), error=MagicMock())
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.load_saga_for_update",
            new_callable=AsyncMock,
            return_value=saga,
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
    ):
        await handle_embedding_callback(message, context)

    terminate.assert_not_awaited()
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_operation_id_is_a_noop() -> None:
    saga = _saga()
    saga.last_dispatch_ids = {"embedding": "op-new"}
    message = _message(str(saga.id))
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.load_saga_for_update",
            new_callable=AsyncMock,
            return_value=saga,
        ),
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
    ):
        await handle_embedding_callback(message, context)

    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_embedding_success_commits_fact_without_qdrant_write() -> None:
    saga = _saga()
    profile = MagicMock()
    message = _message(str(saga.id))
    message.success = MagicMock(
        collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
        content_hash=saga.semantic_hash,
        embeddings=[],
    )
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.load_saga_for_update",
            new_callable=AsyncMock,
            return_value=saga,
        ),
        patch(
            "user_pref_service.events.callbacks.persist_query_enrichment",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.record_success",
            new_callable=AsyncMock,
        ) as record_success,
        patch(
            "user_pref_service.events.callbacks.saga_service.complete_enrichment",
            new_callable=AsyncMock,
        ) as complete,
        patch(
            "user_pref_service.services.profile_vector_service.upsert_profile_point",
            new_callable=AsyncMock,
        ) as qdrant_upsert,
    ):
        await handle_embedding_callback(message, context)

    record_success.assert_awaited_once_with(context.db_session, saga, "embedding")
    complete.assert_awaited_once_with(context.db_session, context.outbox, saga)
    qdrant_upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_hash_mismatch_stays_pending_for_bounded_retry() -> None:
    saga = _saga()
    message = _message(str(saga.id))
    message.success = MagicMock(
        collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
        content_hash="stale-hash",
        embeddings=[],
    )
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.load_saga_for_update",
            new_callable=AsyncMock,
            return_value=saga,
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.record_retryable_error",
            new_callable=AsyncMock,
        ) as record_retry,
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
    ):
        await handle_embedding_callback(message, context)

    record_retry.assert_awaited_once()
    persist.assert_not_awaited()

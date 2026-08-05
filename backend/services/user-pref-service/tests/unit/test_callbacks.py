"""Tests for durable preference enrichment callback classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.ml.v1 import EmbeddingType, EntityType
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_db_utils import SagaStatus
from nohiki_kafka_client import MessageContext
from user_pref_service.core.config import get_manifest
from user_pref_service.core.embedding import PREF_EMBEDDING_SPEC, PrefEnrichmentSagaContext
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
    now = datetime.now(UTC)
    saga.created_at = now
    saga.expires_at = now + timedelta(minutes=2)
    saga.profile = MagicMock()
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
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
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
        assert terminate.await_args is not None
        termination = terminate.await_args.args[4]
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
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
    ):
        await handle_skill_normalization_callback(message, context)

    assert terminate.await_args is not None
    assert terminate.await_args.args[4].reason == PrefEnrichmentFailedFailureReason.SKILL_NORMALIZATION_FAILED


@pytest.mark.asyncio
async def test_cancelled_saga_makes_late_callback_a_noop() -> None:
    saga = _saga(status=SagaStatus.CANCELLED)
    message = _message(str(saga.id), error=MagicMock())
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
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
async def test_expired_success_callback_terminalizes_before_persistence() -> None:
    saga = _saga()
    now = datetime.now(UTC)
    saga.created_at = now - timedelta(minutes=31)
    saga.expires_at = now - timedelta(seconds=1)
    message = _message(str(saga.id))
    message.success = MagicMock()
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
        patch(
            "user_pref_service.events.callbacks.saga_service.complete_enrichment",
            new_callable=AsyncMock,
        ) as complete,
    ):
        await handle_embedding_callback(message, context)

    assert terminate.await_args is not None
    termination = terminate.await_args.args[4]
    assert termination.status == SagaStatus.EXPIRED
    assert termination.reason == PrefEnrichmentFailedFailureReason.EXPIRED
    persist.assert_not_awaited()
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_operation_id_is_a_noop() -> None:
    saga = _saga()
    saga.last_dispatch_ids = {"embedding": "op-new"}
    message = _message(str(saga.id))
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
    ):
        await handle_embedding_callback(message, context)

    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_persisted_callback_is_a_noop() -> None:
    saga = _saga()
    saga.embedding_persisted = True
    message = _message(str(saga.id))
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
    ):
        await handle_embedding_callback(message, context)

    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_embedding_success_commits_exact_requested_types_without_qdrant_write() -> None:
    saga = _saga()
    profile = saga.profile
    message = _message(str(saga.id))
    message.success = MagicMock(
        collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
        content_hash=saga.semantic_hash,
        embeddings=[MagicMock(embedding_type=embedding_type) for embedding_type in PREF_EMBEDDING_SPEC.requested_types],
    )
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch(
            "user_pref_service.events.callbacks.persist_query_enrichment",
            new_callable=AsyncMock,
            return_value=profile,
        ) as persist,
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

    persist.assert_awaited_once_with(
        context.db_session,
        profile,
        message.success,
        expected_generation=saga.semantic_generation,
        expected_hash=saga.semantic_hash,
    )
    record_success.assert_awaited_once_with(context.db_session, saga, "embedding")
    complete.assert_awaited_once_with(context.db_session, context.outbox, profile, saga)
    qdrant_upsert.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "embedding_types",
    [
        [],
        list(PREF_EMBEDDING_SPEC.requested_types[:-1]),
        [*PREF_EMBEDDING_SPEC.requested_types, PREF_EMBEDDING_SPEC.requested_types[-1]],
        [*PREF_EMBEDDING_SPEC.requested_types, EmbeddingType.DENSE],
    ],
    ids=["empty", "partial", "duplicate", "unexpected"],
)
async def test_invalid_embedding_result_types_stay_pending_for_bounded_retry(
    embedding_types: list[EmbeddingType],
) -> None:
    saga = _saga()
    message = _message(str(saga.id))
    message.success = MagicMock(
        collection_version=get_manifest().get_entity_version(EntityType.PROFILE),
        content_hash=saga.semantic_hash,
        embeddings=[MagicMock(embedding_type=embedding_type) for embedding_type in embedding_types],
    )
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.record_retryable_error",
            new_callable=AsyncMock,
        ) as record_retry,
        patch(
            "user_pref_service.events.callbacks.persist_query_enrichment",
            new_callable=AsyncMock,
        ) as persist,
        patch(
            "user_pref_service.events.callbacks.saga_service.record_success",
            new_callable=AsyncMock,
        ) as record_success,
        patch(
            "user_pref_service.events.callbacks.saga_service.complete_enrichment",
            new_callable=AsyncMock,
        ) as complete,
    ):
        await handle_embedding_callback(message, context)

    record_retry.assert_awaited_once()
    assert record_retry.await_args is not None
    assert record_retry.await_args.kwargs["step"] == "embedding"
    assert record_retry.await_args.kwargs["error_code"] == "EMBEDDING_RESULT_TYPES_MISMATCH"
    assert "do not exactly match required types" in record_retry.await_args.kwargs["error_message"]
    persist.assert_not_awaited()
    record_success.assert_not_awaited()
    complete.assert_not_awaited()


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
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
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


@pytest.mark.asyncio
async def test_stale_collection_callback_uses_budgeted_redispatch() -> None:
    saga = _saga()
    message = _message(str(saga.id))
    message.success = MagicMock(
        collection_version="v1",
        content_hash=saga.semantic_hash,
        embeddings=[],
    )
    context = _context()
    with (
        patch(
            "user_pref_service.events.callbacks.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(saga.profile, saga),
        ),
        patch(
            "user_pref_service.events.callbacks.saga_service.retry_enrichment",
            new_callable=AsyncMock,
        ) as retry,
        patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
    ):
        await handle_embedding_callback(message, context)

    retry.assert_awaited_once_with(context.db_session, context.outbox, saga.profile, saga)
    persist.assert_not_awaited()

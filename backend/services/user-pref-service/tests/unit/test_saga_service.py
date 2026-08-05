"""Tests for durable preference enrichment saga transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.ml.v1 import EmbeddingRequested
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_db_utils import OutboxEventParams, SagaStatus
from user_pref_service.core.saga_policy import CALLBACK_TIMEOUT, SagaTermination
from user_pref_service.db.models import PrefEnrichmentAction, PrefEnrichmentSaga
from user_pref_service.services import saga_service


def _saga(*, attempts_remaining: int = 2) -> MagicMock:
    saga = MagicMock()
    saga.id = uuid4()
    saga.pref_id = uuid4()
    saga.user_id = uuid4()
    saga.request_id = uuid4()
    saga.correlation_id = "corr-1"
    saga.status = SagaStatus.PENDING
    saga.created_at = datetime.now(UTC) - timedelta(minutes=1)
    saga.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    saga.attempts_remaining = attempts_remaining
    saga.last_error_message = "downstream unavailable"
    return saga


def _real_saga() -> PrefEnrichmentSaga:
    now = datetime.now(UTC)
    return PrefEnrichmentSaga(
        id=uuid4(),
        pref_id=uuid4(),
        user_id=uuid4(),
        request_id=uuid4(),
        correlation_id="corr-1",
        action=PrefEnrichmentAction.CREATE,
        raw_skills=[],
        last_dispatch_ids={"embedding": "op-1"},
        skills_persisted=False,
        embedding_persisted=False,
        semantic_generation=1,
        semantic_hash="semantic-hash",
        expected_callbacks=1,
        received_callbacks=0,
        created_at=now,
        expires_at=now + timedelta(minutes=2),
        attempts_remaining=2,
        version=1,
        status=SagaStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_create_saga_persists_initial_budget_and_deadline() -> None:
    db = MagicMock(add=MagicMock(), flush=AsyncMock(), refresh=AsyncMock())
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    new = saga_service.NewEnrichmentSaga(
        pref_id=uuid4(),
        user_id=uuid4(),
        request_id=uuid4(),
        correlation_id=str(uuid4()),
        action=PrefEnrichmentAction.CREATE,
        raw_skills=[],
        semantic_generation=1,
        semantic_hash="a" * 64,
    )

    with patch("user_pref_service.services.saga_service.datetime") as clock:
        clock.now.return_value = created_at
        saga = await saga_service.create_enrichment_saga(db, new)

    db.add.assert_called_once_with(saga)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(saga)
    assert saga.attempts_remaining == saga_service.MAX_ATTEMPTS - 1
    assert saga.expires_at == created_at + CALLBACK_TIMEOUT
    clock.now.assert_called_once_with(UTC)


@pytest.mark.asyncio
async def test_lock_profile_then_saga_uses_canonical_row_order() -> None:
    saga = _real_saga()
    profile = MagicMock(id=saga.pref_id)
    owner_result = MagicMock()
    owner_result.scalar_one_or_none.return_value = saga.pref_id
    order: list[str] = []

    async def read_owner(_statement: object) -> MagicMock:
        order.append("owner_read")
        return owner_result

    async def lock_profile(_db: object, pref_id: object) -> MagicMock:
        assert pref_id == saga.pref_id
        order.append("profile_lock")
        return profile

    async def lock_saga(_db: object, saga_id: object) -> PrefEnrichmentSaga:
        assert saga_id == saga.id
        order.append("saga_lock")
        return saga

    db = MagicMock(execute=AsyncMock(side_effect=read_owner))
    with (
        patch(
            "user_pref_service.services.saga_service.profile_service.get_profile_by_id_for_update",
            side_effect=lock_profile,
        ),
        patch(
            "user_pref_service.services.saga_service.load_saga_for_update",
            side_effect=lock_saga,
        ),
    ):
        locked = await saga_service.lock_profile_then_saga(db, saga.id)

    assert locked == (profile, saga)
    assert order == ["owner_read", "profile_lock", "saga_lock"]


@pytest.mark.asyncio
async def test_lock_profile_then_saga_ignores_missing_saga_before_profile_lock() -> None:
    owner_result = MagicMock()
    owner_result.scalar_one_or_none.return_value = None
    db = MagicMock(execute=AsyncMock(return_value=owner_result))
    with patch(
        "user_pref_service.services.saga_service.profile_service.get_profile_by_id_for_update",
        new_callable=AsyncMock,
    ) as lock_profile:
        assert await saga_service.lock_profile_then_saga(db, uuid4()) is None

    lock_profile.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["skill", "embedding"])
async def test_record_success_clears_error_and_counts_each_step(step: str) -> None:
    saga = _real_saga()
    saga.failed_step = "old"
    saga.last_error_code = "TEMPORARY"
    saga.last_error_message = "retry"
    db = MagicMock(flush=AsyncMock())

    await saga_service.record_success(db, saga, step)

    assert saga.received_callbacks == 1
    assert saga.skills_persisted is (step == "skill")
    assert saga.embedding_persisted is (step == "embedding")
    assert saga.failed_step is None
    assert saga.last_error_code is None
    assert saga.last_error_message is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_persists_operation_identity_and_preserves_late_deadline() -> None:
    saga = _real_saga()
    original_deadline = datetime.now(UTC) - timedelta(minutes=10)
    saga.expires_at = original_deadline
    saga.last_dispatch_ids = {}
    profile = MagicMock()
    timeline: list[str] = []
    db = MagicMock(flush=AsyncMock(side_effect=lambda: timeline.append("identity_flushed")))
    outbox = MagicMock()

    async def write_outbound(*, db: object, params: OutboxEventParams, event: EmbeddingRequested) -> None:
        assert db is not None
        assert saga.last_dispatch_ids["embedding"] == event.command.operation_id
        assert params.event_type
        timeline.append("outbox_written")

    async def direct_publish(**_kwargs: object) -> str:
        timeline.append("direct_publish_before_commit")
        return "direct-operation"

    outbox.write_event = AsyncMock(side_effect=write_outbound)
    publisher = MagicMock(request_embedding=AsyncMock(side_effect=direct_publish))
    with (
        patch(
            "user_pref_service.services.saga_service.profile_service.get_profile_by_id",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "user_pref_service.services.saga_service.profile_service.build_profile_embedding_text_from_profile",
            return_value="python platform",
        ),
        patch("user_pref_service.services.saga_service.get_embedding_publisher", return_value=publisher),
    ):
        operation_id = await saga_service.dispatch_next_step(db, outbox, saga)

    assert saga.last_dispatch_ids == {"embedding": operation_id}
    assert saga.expires_at == original_deadline
    assert timeline == ["identity_flushed", "outbox_written"]
    publisher.request_embedding.assert_not_awaited()


@pytest.mark.asyncio
async def test_retryable_callback_preserves_original_deadline_after_slow_execution() -> None:
    saga = _real_saga()
    now = datetime.now(UTC)
    original_deadline = now - timedelta(minutes=10)
    saga.created_at = now - timedelta(hours=1)
    saga.expires_at = original_deadline
    db = MagicMock(flush=AsyncMock())

    await saga_service.record_retryable_error(
        db,
        saga,
        step="embedding",
        error_code="TEMPORARY",
        error_message="retry later",
    )

    assert saga.expires_at == original_deadline


@pytest.mark.asyncio
async def test_every_redispatch_consumes_budget_and_zero_budget_terminalizes() -> None:
    saga = _real_saga()
    saga.attempts_remaining = 1
    db = MagicMock()
    outbox = MagicMock()
    profile = MagicMock()
    with (
        patch(
            "user_pref_service.services.saga_service.dispatch_next_step",
            new_callable=AsyncMock,
        ) as dispatch,
        patch(
            "user_pref_service.services.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
    ):
        assert await saga_service.retry_enrichment(db, outbox, profile, saga) is True
        assert saga.attempts_remaining == 0
        assert await saga_service.retry_enrichment(db, outbox, profile, saga) is False

    dispatch.assert_awaited_once_with(db, outbox, saga, profile)
    assert terminate.await_args is not None
    termination = terminate.await_args.args[4]
    assert termination.status == SagaStatus.EXPIRED
    assert termination.reason == PrefEnrichmentFailedFailureReason.EXPIRED


@pytest.mark.asyncio
async def test_terminal_failure_updates_profile_and_writes_correlated_fact() -> None:
    saga = _real_saga()
    profile = MagicMock(enrichment_terminal_status=None)
    db = MagicMock(flush=AsyncMock())
    outbox = MagicMock()
    with patch(
        "user_pref_service.services.saga_service.publish_pref_enrichment_failed",
        new_callable=AsyncMock,
    ) as publish:
        await saga_service.terminate_enrichment(
            db,
            outbox,
            profile,
            saga,
            SagaTermination(
                status=SagaStatus.FAILED,
                reason=PrefEnrichmentFailedFailureReason.EMBEDDING_FAILED,
                error_message="permanent model rejection",
            ),
        )

    assert saga.status == SagaStatus.FAILED
    assert profile.enrichment_terminal_status == "failed"
    publish.assert_awaited_once_with(
        db,
        outbox,
        saga,
        reason=PrefEnrichmentFailedFailureReason.EMBEDDING_FAILED,
        error_message="permanent model rejection",
    )


@pytest.mark.asyncio
async def test_expired_budget_transitions_and_emits_failure() -> None:
    saga = _saga(attempts_remaining=0)
    profile = MagicMock()
    result = MagicMock()
    result.scalars.return_value = [saga.id]
    db = MagicMock(execute=AsyncMock(return_value=result))
    outbox = MagicMock()
    with (
        patch(
            "user_pref_service.services.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(profile, saga),
        ),
        patch(
            "user_pref_service.services.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
        patch(
            "user_pref_service.services.saga_service.dispatch_next_step",
            new_callable=AsyncMock,
        ) as dispatch,
    ):
        count = await saga_service.sweep_due_enrichment_sagas(db, outbox)

    assert count == 1
    dispatch.assert_not_awaited()
    assert terminate.await_args is not None
    termination = terminate.await_args.args[4]
    assert termination.status == SagaStatus.EXPIRED
    assert termination.reason == PrefEnrichmentFailedFailureReason.EXPIRED


@pytest.mark.asyncio
async def test_due_deadline_expires_without_redispatch() -> None:
    saga = _saga(attempts_remaining=2)
    profile = MagicMock()
    result = MagicMock()
    result.scalars.return_value = [saga.id]
    db = MagicMock(execute=AsyncMock(return_value=result))
    outbox = MagicMock()
    with (
        patch(
            "user_pref_service.services.saga_service.lock_profile_then_saga",
            new_callable=AsyncMock,
            return_value=(profile, saga),
        ),
        patch(
            "user_pref_service.services.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
        patch(
            "user_pref_service.services.saga_service.dispatch_next_step",
            new_callable=AsyncMock,
        ) as dispatch,
    ):
        await saga_service.sweep_due_enrichment_sagas(db, outbox)

    assert saga.attempts_remaining == 2
    dispatch.assert_not_awaited()
    assert terminate.await_args is not None
    assert terminate.await_args.args[4].status == SagaStatus.EXPIRED


@pytest.mark.asyncio
async def test_cancellation_transitions_every_pending_saga() -> None:
    first, second = _saga(), _saga()
    db = MagicMock()
    profile = MagicMock(id=first.pref_id)
    outbox = MagicMock()
    with (
        patch(
            "user_pref_service.services.saga_service.find_pending_sagas_for_update",
            new_callable=AsyncMock,
            return_value=[first, second],
        ),
        patch(
            "user_pref_service.services.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
    ):
        await saga_service.cancel_pending_enrichment(
            db,
            outbox,
            profile,
            message="profile deleted",
        )

    assert terminate.await_count == 2
    terminations = [call.args[4] for call in terminate.await_args_list]
    assert all(termination.status == SagaStatus.CANCELLED for termination in terminations)
    assert all(termination.reason == PrefEnrichmentFailedFailureReason.CANCELLED for termination in terminations)

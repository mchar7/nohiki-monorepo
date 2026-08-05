"""Tests for durable preference enrichment saga transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_db_utils import SagaStatus
from user_pref_service.core.saga_policy import SagaTermination
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
async def test_terminal_failure_updates_profile_and_writes_correlated_fact() -> None:
    saga = _real_saga()
    profile = MagicMock(enrichment_terminal_status=None)
    db = MagicMock(flush=AsyncMock())
    outbox = MagicMock()
    with (
        patch(
            "user_pref_service.services.saga_service.profile_service.get_profile_by_id_optional",
            new_callable=AsyncMock,
            return_value=profile,
        ),
        patch(
            "user_pref_service.services.saga_service.publish_pref_enrichment_failed",
            new_callable=AsyncMock,
        ) as publish,
    ):
        await saga_service.terminate_enrichment(
            db,
            outbox,
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
    result = MagicMock()
    result.scalars.return_value.all.return_value = [saga]
    db = MagicMock(execute=AsyncMock(return_value=result))
    with (
        patch(
            "user_pref_service.services.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
        patch(
            "user_pref_service.services.saga_service.dispatch_next_step",
            new_callable=AsyncMock,
        ) as dispatch,
    ):
        count = await saga_service.sweep_due_enrichment_sagas(db, MagicMock())

    assert count == 1
    dispatch.assert_not_awaited()
    termination = terminate.await_args.args[3]
    assert termination.status == SagaStatus.EXPIRED
    assert termination.reason == PrefEnrichmentFailedFailureReason.EXPIRED


@pytest.mark.asyncio
async def test_due_retry_consumes_one_attempt_without_expiring() -> None:
    saga = _saga(attempts_remaining=2)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [saga]
    db = MagicMock(execute=AsyncMock(return_value=result))
    with (
        patch(
            "user_pref_service.services.saga_service.terminate_enrichment",
            new_callable=AsyncMock,
        ) as terminate,
        patch(
            "user_pref_service.services.saga_service.dispatch_next_step",
            new_callable=AsyncMock,
        ) as dispatch,
    ):
        await saga_service.sweep_due_enrichment_sagas(db, MagicMock())

    assert saga.attempts_remaining == 1
    dispatch.assert_awaited_once_with(db, saga)
    terminate.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_transitions_every_pending_saga() -> None:
    first, second = _saga(), _saga()
    db = MagicMock()
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
            first.pref_id,
            message="profile deleted",
        )

    assert terminate.await_count == 2
    terminations = [call.args[3] for call in terminate.await_args_list]
    assert all(termination.status == SagaStatus.CANCELLED for termination in terminations)
    assert all(termination.reason == PrefEnrichmentFailedFailureReason.CANCELLED for termination in terminations)

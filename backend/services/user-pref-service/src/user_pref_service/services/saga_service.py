"""Durable lifecycle and retry operations for preference enrichment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.common.v1 import CommandHeader
from nohiki.ml.v1 import EmbeddingRequested, EntityType
from nohiki.skill.v1 import SkillNormalizationRequested
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_db_utils import OutboxEventParams, SagaStatus
from nohiki_kafka_client import Topics, create_event_metadata
from sqlalchemy import or_, select
from uuid_utils.compat import uuid7

from user_pref_service.core.config import get_settings
from user_pref_service.core.embedding import (
    PREF_EMBEDDING_SPEC,
    PrefEnrichmentSagaContext,
    get_embedding_publisher,
)
from user_pref_service.core.saga_policy import (
    CALLBACK_TIMEOUT,
    MAX_ATTEMPTS,
    WALL_CLOCK_CAP,
    NewEnrichmentSaga,
    SagaTermination,
)
from user_pref_service.db.models import PrefEnrichmentAction, PrefEnrichmentSaga
from user_pref_service.events.publishers import (
    publish_pref_enrichment_failed,
    publish_profile_created_event,
    publish_profile_updated_event,
)
from user_pref_service.services import profile_service
from user_pref_service.services.enrichment_completion import load_user_skills_from_profile

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession


def _action_value(saga: PrefEnrichmentSaga) -> str:
    action = saga.action
    return (action.value if isinstance(action, PrefEnrichmentAction) else str(action)).lower()


async def create_enrichment_saga(db: AsyncSession, new: NewEnrichmentSaga) -> PrefEnrichmentSaga:
    """Create one request-owned saga with an initial dispatch plus two retries."""
    saga = PrefEnrichmentSaga(
        pref_id=new.pref_id,
        user_id=new.user_id,
        request_id=new.request_id,
        correlation_id=new.correlation_id,
        action=new.action,
        raw_skills=new.raw_skills,
        semantic_generation=new.semantic_generation,
        semantic_hash=new.semantic_hash,
        expected_callbacks=2 if new.raw_skills else 1,
        expires_at=datetime.now(UTC) + CALLBACK_TIMEOUT,
        attempts_remaining=MAX_ATTEMPTS - 1,
    )
    db.add(saga)
    await db.flush()
    await db.refresh(saga)
    return saga


async def get_saga_by_request_id(db: AsyncSession, request_id: UUID) -> PrefEnrichmentSaga | None:
    """Load the saga created for an idempotent command request."""
    result = await db.execute(select(PrefEnrichmentSaga).where(PrefEnrichmentSaga.request_id == request_id))
    return result.scalar_one_or_none()


async def load_saga_for_update(db: AsyncSession, saga_id: UUID) -> PrefEnrichmentSaga | None:
    """Lock a saga before validating or changing callback progress."""
    result = await db.execute(select(PrefEnrichmentSaga).where(PrefEnrichmentSaga.id == saga_id).with_for_update())
    return result.scalar_one_or_none()


async def find_pending_sagas_for_update(db: AsyncSession, pref_id: UUID) -> list[PrefEnrichmentSaga]:
    """Lock every pending saga owned by a profile."""
    result = await db.execute(
        select(PrefEnrichmentSaga)
        .where(
            PrefEnrichmentSaga.pref_id == pref_id,
            PrefEnrichmentSaga.status == SagaStatus.PENDING,
        )
        .order_by(PrefEnrichmentSaga.created_at, PrefEnrichmentSaga.id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def dispatch_next_step(
    db: AsyncSession,
    outbox: OutboxWriter,
    saga: PrefEnrichmentSaga,
) -> str:
    """Persist an operation identity and its outbound command atomically."""
    state = PrefEnrichmentSagaContext(saga_id=str(saga.id))
    operation_id = str(uuid7())
    if saga.raw_skills and not saga.skills_persisted:
        step = "skill"
        topic = Topics.SKILL_NORMALIZATION_REQUESTED
        command = SkillNormalizationRequested(
            metadata=create_event_metadata(get_settings().service_name, saga.correlation_id),
            command=CommandHeader(
                operation_id=operation_id,
                callback_topic=Topics.USER_PREF_SKILL_CALLBACK,
                caller_context=state.to_bytes(),
            ),
            canonical_skill_ids=saga.raw_skills,
        )
    else:
        step = "embedding"
        profile = await profile_service.get_profile_by_id(db, saga.pref_id)
        publisher = get_embedding_publisher()
        command = EmbeddingRequested(
            metadata=create_event_metadata(publisher.service_name),
            command=CommandHeader(
                operation_id=operation_id,
                callback_topic=publisher.callback_topic,
                caller_context=state.to_bytes(),
            ),
            entity_id=str(saga.pref_id),
            entity_type=EntityType.PROFILE,
            text=profile_service.build_profile_embedding_text_from_profile(profile),
            collection_version=publisher.collection_version,
            requested_types=list(PREF_EMBEDDING_SPEC.requested_types),
            encoding_mode=PREF_EMBEDDING_SPEC.encoding_mode,
            publish_to_index=PREF_EMBEDDING_SPEC.publish_to_index,
        )
        topic = Topics.ML_EMBEDDING_REQUESTED

    saga.last_dispatch_ids = saga.last_dispatch_ids | {step: operation_id}
    saga.failed_step = None
    saga.last_error_code = None
    saga.last_error_message = None
    saga.expires_at = min(datetime.now(UTC) + CALLBACK_TIMEOUT, saga.created_at + WALL_CLOCK_CAP)
    saga.version += 1
    await db.flush()
    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type="pref_enrichment_dispatch",
            aggregate_id=str(saga.id),
            event_type=topic,
            correlation_id=saga.correlation_id,
        ),
        event=command,
    )
    return operation_id


def operation_matches(saga: PrefEnrichmentSaga, step: str, operation_id: str) -> bool:
    """Reject callbacks from superseded retry dispatches."""
    return saga.last_dispatch_ids.get(step) == operation_id


async def record_success(db: AsyncSession, saga: PrefEnrichmentSaga, step: str) -> None:
    """Record one unique successful callback."""
    if step == "skill":
        saga.skills_persisted = True
    else:
        saga.embedding_persisted = True
    saga.received_callbacks += 1
    saga.failed_step = None
    saga.last_error_code = None
    saga.last_error_message = None
    saga.version += 1
    await db.flush()


async def record_retryable_error(
    db: AsyncSession,
    saga: PrefEnrichmentSaga,
    *,
    step: str,
    error_code: str,
    error_message: str,
) -> None:
    """Leave the saga pending for the durable sweeper."""
    saga.failed_step = step
    saga.last_error_code = error_code[:64]
    saga.last_error_message = error_message[:512]
    saga.expires_at = min(datetime.now(UTC) + CALLBACK_TIMEOUT, saga.created_at + WALL_CLOCK_CAP)
    saga.version += 1
    await db.flush()


async def retry_enrichment(
    db: AsyncSession,
    outbox: OutboxWriter,
    saga: PrefEnrichmentSaga,
) -> bool:
    """Consume one retry budget unit or terminalize an exhausted saga."""
    now = datetime.now(UTC)
    if saga.attempts_remaining == 0 or saga.created_at + WALL_CLOCK_CAP <= now:
        await terminate_enrichment(
            db,
            outbox,
            saga,
            SagaTermination(
                status=SagaStatus.EXPIRED,
                reason=PrefEnrichmentFailedFailureReason.EXPIRED,
                error_message=saga.last_error_message or "Preference enrichment deadline expired",
            ),
        )
        return False
    saga.attempts_remaining -= 1
    await dispatch_next_step(db, outbox, saga)
    return True


async def complete_enrichment(
    db: AsyncSession,
    outbox: OutboxWriter,
    saga: PrefEnrichmentSaga,
) -> None:
    """Atomically mark completion and write the authoritative lifecycle fact."""
    if not saga.is_complete:
        msg = f"Saga {saga.id} completed before all callbacks arrived"
        raise ValueError(msg)
    profile = await profile_service.get_profile_by_id_for_update(db, saga.pref_id)
    saga.transition_to(SagaStatus.COMPLETED)
    profile.enrichment_terminal_status = None
    user_skills = load_user_skills_from_profile(profile)
    if _action_value(saga) == "update":
        await publish_profile_updated_event(
            db, outbox, profile, user_skills=user_skills, correlation_id=saga.correlation_id
        )
    else:
        await publish_profile_created_event(
            db, outbox, profile, user_skills=user_skills, correlation_id=saga.correlation_id
        )
    await db.flush()


async def terminate_enrichment(
    db: AsyncSession,
    outbox: OutboxWriter,
    saga: PrefEnrichmentSaga,
    termination: SagaTermination,
) -> None:
    """Atomically persist terminal state, profile status, and failure fact."""
    if saga.status != SagaStatus.PENDING:
        return
    saga.transition_to(termination.status)
    profile = await profile_service.get_profile_by_id_optional(db, saga.pref_id)
    if profile is not None:
        profile.enrichment_terminal_status = termination.status.value.lower()
    saga.last_error_message = termination.error_message[:512]
    await publish_pref_enrichment_failed(
        db,
        outbox,
        saga,
        reason=termination.reason,
        error_message=termination.error_message,
    )
    await db.flush()


async def cancel_pending_enrichment(
    db: AsyncSession,
    outbox: OutboxWriter,
    pref_id: UUID,
    *,
    message: str,
) -> None:
    """Cancel active work so every later callback is a no-op."""
    for saga in await find_pending_sagas_for_update(db, pref_id):
        await terminate_enrichment(
            db,
            outbox,
            saga,
            SagaTermination(
                status=SagaStatus.CANCELLED,
                reason=PrefEnrichmentFailedFailureReason.CANCELLED,
                error_message=message,
            ),
        )


async def sweep_due_enrichment_sagas(db: AsyncSession, outbox: OutboxWriter) -> int:
    """Retry due work or expire it after the bounded budget or wall-clock cap."""
    now = datetime.now(UTC)
    result = await db.execute(
        select(PrefEnrichmentSaga)
        .where(
            PrefEnrichmentSaga.status == SagaStatus.PENDING,
            or_(
                PrefEnrichmentSaga.expires_at <= now,
                PrefEnrichmentSaga.created_at <= now - WALL_CLOCK_CAP,
            ),
        )
        .order_by(PrefEnrichmentSaga.expires_at, PrefEnrichmentSaga.id)
        .limit(100)
        .with_for_update(skip_locked=True)
    )
    sagas = list(result.scalars().all())
    for saga in sagas:
        await retry_enrichment(db, outbox, saga)
    return len(sagas)

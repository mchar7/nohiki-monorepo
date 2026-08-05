"""Durable skill-normalization and embedding callback handlers."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import ErrorInfo
from nohiki.ml.v1 import EmbeddingCallback, EmbeddingType, EntityType
from nohiki.skill.v1 import SkillNormalizationCallback
from nohiki.user.pref.v1 import PrefEnrichmentFailedFailureReason
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import SagaStatus
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from user_pref_service.core.config import get_manifest, get_settings
from user_pref_service.core.embedding import PrefEnrichmentSagaContext, profile_embedding_content_hash
from user_pref_service.core.kafka import kafka_client
from user_pref_service.core.saga_policy import SagaTermination
from user_pref_service.db.models import PrefEnrichmentSaga
from user_pref_service.services import profile_service, saga_service
from user_pref_service.services.enrichment_completion import (
    persist_query_enrichment,
    persist_skill_enrichment,
)

logger = get_logger(__name__)
settings = get_settings()


def _callback_operation_id(message: SkillNormalizationCallback | EmbeddingCallback) -> str:
    return message.callback.operation_id


async def _load_current_saga(
    context: MessageContext,
    message: SkillNormalizationCallback | EmbeddingCallback,
    *,
    step: str,
) -> tuple[AsyncSession, PrefEnrichmentSaga | None]:
    state = PrefEnrichmentSagaContext.from_bytes(message.callback.caller_context)
    db = context.require_db_session()
    saga = await saga_service.load_saga_for_update(db, UUID(state.saga_id))
    if saga is None or saga.status != SagaStatus.PENDING:
        logger.info("Ignoring callback for non-pending preference saga", saga_id=state.saga_id, step=step)
        return db, None
    if not saga_service.operation_matches(saga, step, _callback_operation_id(message)):
        logger.info(
            "Ignoring stale preference enrichment callback",
            saga_id=state.saga_id,
            step=step,
            operation_id=_callback_operation_id(message),
        )
        return db, None
    if (step == "skill" and saga.skills_persisted) or (step == "embedding" and saga.embedding_persisted):
        logger.info("Ignoring duplicate preference enrichment callback", saga_id=state.saga_id, step=step)
        return db, None
    return db, saga


async def _handle_declared_error(
    context: MessageContext,
    saga: PrefEnrichmentSaga,
    *,
    step: str,
    error: ErrorInfo,
) -> None:
    db = context.require_db_session()
    if error.retryable:
        await saga_service.record_retryable_error(
            db,
            saga,
            step=step,
            error_code=error.error_code,
            error_message=error.error_message,
        )
        logger.warning(
            "Preference enrichment step left pending for retry",
            saga_id=str(saga.id),
            step=step,
            error_code=error.error_code,
        )
        return
    reason = (
        PrefEnrichmentFailedFailureReason.SKILL_NORMALIZATION_FAILED
        if step == "skill"
        else PrefEnrichmentFailedFailureReason.EMBEDDING_FAILED
    )
    await saga_service.terminate_enrichment(
        db,
        context.require_outbox(),
        saga,
        SagaTermination(
            status=SagaStatus.FAILED,
            reason=reason,
            error_message=error.error_message or error.error_code,
        ),
    )


@kafka_client.message_handler(
    Topics.USER_PREF_SKILL_CALLBACK,
    SkillNormalizationCallback,
    group_id="user-pref-skill-completed-primary",
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_skill_normalization_callback(
    message: SkillNormalizationCallback,
    context: MessageContext,
) -> None:
    """Persist one operation-matched skill callback or classify its typed error."""
    db, saga = await _load_current_saga(context, message, step="skill")
    if saga is None:
        return
    if (error := message.error) is not None:
        await _handle_declared_error(context, saga, step="skill", error=error)
        return
    if (success := message.success) is None:
        msg = "Empty skill normalization callback result"
        raise ValidationError(msg)

    profile = await persist_skill_enrichment(
        db,
        saga.pref_id,
        success,
        expected_generation=saga.semantic_generation,
    )
    if profile is None:
        logger.info("Ignoring superseded skill callback", saga_id=str(saga.id))
        return
    embedding_text = profile_service.build_profile_embedding_text_from_profile(profile)
    semantic_hash = profile_embedding_content_hash(embedding_text)
    profile.semantic_content_hash = semantic_hash
    saga.semantic_hash = semantic_hash
    await saga_service.record_success(db, saga, "skill")
    await saga_service.dispatch_next_step(db, saga)


@kafka_client.message_handler(
    Topics.USER_PREF_EMBEDDING_CALLBACK,
    EmbeddingCallback,
    group_id="user-pref-embedding-callback-primary",
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_embedding_callback(message: EmbeddingCallback, context: MessageContext) -> None:
    """Commit persisted query vectors, saga completion, and lifecycle fact atomically."""
    db, saga = await _load_current_saga(context, message, step="embedding")
    if saga is None:
        return
    if (error := message.error) is not None:
        await _handle_declared_error(context, saga, step="embedding", error=error)
        return
    if (success := message.success) is None:
        msg = "Empty embedding callback result"
        raise ValidationError(msg)

    current_version = get_manifest().get_entity_version(EntityType.PROFILE)
    if success.collection_version != current_version:
        await saga_service.dispatch_next_step(db, saga)
        logger.info(
            "Replaced stale-version preference embedding callback",
            saga_id=str(saga.id),
            callback_version=success.collection_version,
            current_version=current_version,
        )
        return
    callback_hash = success.content_hash if isinstance(success.content_hash, str) else ""
    if callback_hash and callback_hash != saga.semantic_hash:
        await saga_service.record_retryable_error(
            db,
            saga,
            step="embedding",
            error_code="CONTENT_HASH_MISMATCH",
            error_message="Embedding callback content hash does not match the active preference workflow",
        )
        return

    profile = await persist_query_enrichment(
        db,
        saga.pref_id,
        success,
        expected_generation=saga.semantic_generation,
        expected_hash=saga.semantic_hash,
    )
    if profile is None:
        logger.info("Ignoring superseded embedding callback", saga_id=str(saga.id))
        return
    await saga_service.record_success(db, saga, "embedding")
    await saga_service.complete_enrichment(db, context.require_outbox(), saga)
    logger.info(
        "Preference enrichment completed",
        saga_id=str(saga.id),
        pref_id=str(saga.pref_id),
        retrieval_types=[
            embedding.embedding_type.name
            for embedding in success.embeddings
            if embedding.embedding_type != EmbeddingType.DENSE
        ],
    )

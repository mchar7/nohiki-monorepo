"""Callback handlers for enrichment completions.

Handles skill normalization and embedding callbacks from downstream services.
State is carried via ECST (PrefEmbeddingState in CommandHeader.caller_context).
Full user skill data is persisted to the DB by persist_skill_enrichment so that
handle_embedding_callback can load it from the profile row without needing to
carry it inline: keeping PrefEmbeddingState at ~80 bytes per the plan.

Flow:
  SkillNormalizationCallback (success) → persist full skill data to DB → request query embedding
  EmbeddingCallback (success)          → persist embedding → load skills from DB → publish lifecycle event
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from nohiki.ml.v1 import EmbeddingCallback, EmbeddingResult, EntityType
from nohiki.skill.v1 import SkillNormalizationCallback, SkillNormalizationResult
from nohiki_common_exceptions import ValidationError
from nohiki_kafka_client import CommandContext, MessageContext, Topics
from nohiki_observability import get_logger

from user_pref_service.core.config import get_manifest, get_settings
from user_pref_service.core.embedding import (
    PREF_EMBEDDING_SPEC,
    PrefEmbeddingState,
    build_profile_embedding_text,
    get_embedding_publisher,
    profile_embedding_content_hash,
)
from user_pref_service.core.kafka import kafka_client
from user_pref_service.db.models import SearchPref
from user_pref_service.events.publishers import (
    publish_profile_created_event,
    publish_profile_updated_event,
)
from user_pref_service.services import profile_service
from user_pref_service.services.enrichment_completion import (
    load_user_skills_from_profile,
    persist_query_enrichment,
    persist_skill_enrichment,
)
from user_pref_service.services.profile_vector_service import upsert_profile_point

logger = get_logger(__name__)
settings = get_settings()


class _PrefAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"


def _state_matches_profile(profile: SearchPref, state: PrefEmbeddingState) -> bool:
    """Check callback identity against the current persisted semantic state."""
    if state.semantic_generation and getattr(profile, "semantic_content_generation", None) != state.semantic_generation:
        return False
    if state.semantic_hash:
        return getattr(profile, "semantic_content_hash", None) == state.semantic_hash
    if state.embedded_text:
        try:
            current_text = profile_service.build_profile_embedding_text_from_profile(profile)
            return profile_embedding_content_hash(current_text) == profile_embedding_content_hash(state.embedded_text)
        except TypeError, ValueError, ValidationError:
            return False
    return True


def _persisted_embedding_text(profile: SearchPref, fallback: str) -> str:
    """Build text from persisted fields, retaining legacy callback fallback."""
    try:
        text = profile_service.build_profile_embedding_text_from_profile(profile)
    except TypeError, ValueError, ValidationError:
        return fallback
    return text or fallback


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
    """Persist skills and defer query embedding via fire-and-forget.

    Deserializes PrefEmbeddingState from caller_context, persists the full
    skill normalization result (embedding vector + canonical IDs + UserSkillEntry
    data) to the DB, then either requests async query embedding (when query text
    exists) or publishes the lifecycle event immediately (when not).
    On error, logs and returns: downstream retry re-delivers.
    """
    state = PrefEmbeddingState.from_bytes(message.callback.caller_context)
    pref_id = UUID(state.pref_id)

    if (success := message.success) is not None:
        await _process_normalization_success(success, state, pref_id, context)
    elif (error := message.error) is not None:
        logger.error(
            "Skill normalization failed -- enrichment aborted",
            pref_id=str(pref_id),
            action=state.action,
            error_code=error.error_code,
            error_message=error.error_message,
        )
    else:
        msg = "Empty skill normalization callback result"
        raise ValidationError(msg)


async def _process_normalization_success(
    success: SkillNormalizationResult,
    state: PrefEmbeddingState,
    pref_id: UUID,
    context: MessageContext,
) -> None:
    """Persist full skill data to DB then trigger query embedding or publish immediately."""
    db = context.require_db_session()
    persist_kwargs = {"expected_generation": state.semantic_generation} if state.semantic_generation else {}
    profile = await persist_skill_enrichment(db, pref_id, success, **persist_kwargs)
    if profile is None:
        logger.info("Discarded stale skill normalization callback", pref_id=str(pref_id))
        return

    try:
        embedding_text = profile_service.build_profile_embedding_text_from_profile(profile)
    except TypeError, ValueError, ValidationError:
        keywords = profile.search_keywords if isinstance(getattr(profile, "search_keywords", None), list) else []
        skill_names = [
            req.skill_name for req in success.skill_requirements if isinstance(req.skill_name, str) and req.skill_name
        ]
        embedding_text = build_profile_embedding_text(
            str(getattr(profile, "pref_name", "")),
            keywords,
            skill_names,
        )
    semantic_generation = profile.semantic_content_generation
    if not isinstance(getattr(profile, "user_skills_data", None), list) and success.skill_requirements:
        skill_names = [
            req.skill_name for req in success.skill_requirements if isinstance(req.skill_name, str) and req.skill_name
        ]
        keywords = profile.search_keywords if isinstance(getattr(profile, "search_keywords", None), list) else []
        embedding_text = build_profile_embedding_text(str(getattr(profile, "pref_name", "")), keywords, skill_names)
    semantic_hash = profile_service.set_profile_semantic_hash(profile, embedding_text)
    await db.flush()
    embedding_state = PrefEmbeddingState(
        pref_id=state.pref_id,
        action=state.action,
        embedded_text=embedding_text
        if not isinstance(semantic_generation, int) and isinstance(getattr(profile, "pref_name", None), str)
        else "",
        semantic_hash=semantic_hash if isinstance(semantic_generation, int) else "",
    )
    await _request_query_embedding(embedding_text, embedding_state, pref_id)


async def _request_query_embedding(
    query_text: str,
    state: PrefEmbeddingState,
    pref_id: UUID,
) -> None:
    """Publish a QUERY-mode profile embedding after skill normalization."""
    publisher = get_embedding_publisher()
    operation_id = await publisher.request_embedding(
        text=query_text,
        entity_id=str(pref_id),
        entity_type=EntityType.PROFILE,
        spec=PREF_EMBEDDING_SPEC,
        context=CommandContext(caller_context=state.to_bytes()),
    )
    logger.info(
        "Query embedding requested after skill normalization",
        pref_id=str(pref_id),
        action=state.action,
        operation_id=operation_id,
    )


@kafka_client.message_handler(
    Topics.USER_PREF_EMBEDDING_CALLBACK,
    EmbeddingCallback,
    group_id="user-pref-embedding-callback-primary",
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_embedding_callback(
    message: EmbeddingCallback,
    context: MessageContext,
) -> None:
    """Persist query embedding and publish lifecycle event on success.

    Deserializes PrefEmbeddingState from caller_context, persists the retrieval
    vectors, marks enrichment complete, loads user skills from the DB (persisted
    during the skill normalization stage), then publishes the lifecycle event.
    On error, logs the downstream-declared failure and acknowledges the callback.
    """
    state = PrefEmbeddingState.from_bytes(message.callback.caller_context)
    pref_id = UUID(state.pref_id)

    if (success := message.success) is not None:
        await _process_embedding_success(success, state, pref_id, context)
    elif (error := message.error) is not None:
        logger.error(
            "Embedding failed -- enrichment aborted",
            pref_id=str(pref_id),
            action=state.action,
            error_code=error.error_code,
            error_message=error.error_message,
        )
    else:
        msg = "Empty embedding callback result"
        raise ValidationError(msg)


async def _process_embedding_success(
    success: EmbeddingResult,
    state: PrefEmbeddingState,
    pref_id: UUID,
    context: MessageContext,
) -> None:
    """Persist query embedding vectors and publish lifecycle event.

    User skills are loaded from the DB profile row (user_skills_data column)
    rather than from ECST state, keeping PrefEmbeddingState at ~80 bytes.
    """
    db = context.require_db_session()
    current_version = get_manifest().get_entity_version(EntityType.PROFILE)
    if success.collection_version != current_version:
        profile = await profile_service.get_profile_by_id(db, pref_id)
        if not _state_matches_profile(profile, state):
            logger.info("Discarded stale profile embedding callback", pref_id=str(pref_id))
            return
        retry_text = _persisted_embedding_text(profile, state.embedded_text)
        await _request_query_embedding(retry_text, state, pref_id)
        logger.info(
            "Stale profile embedding callback replaced",
            pref_id=str(pref_id),
            callback_version=success.collection_version,
            current_version=current_version,
        )
        return
    callback_hash = success.content_hash if isinstance(success.content_hash, str) else ""
    if state.semantic_hash and callback_hash and callback_hash != state.semantic_hash:
        logger.info("Discarded profile embedding with mismatched content hash", pref_id=str(pref_id))
        return
    expected_hash = (
        state.semantic_hash
        or callback_hash
        or (profile_embedding_content_hash(state.embedded_text) if state.embedded_text else "")
    )

    expected_generation = state.semantic_generation or None
    if expected_generation is not None and expected_hash:
        profile = await persist_query_enrichment(
            db,
            pref_id,
            success,
            expected_generation=expected_generation,
            expected_hash=expected_hash,
        )
    elif expected_generation is not None:
        profile = await persist_query_enrichment(db, pref_id, success, expected_generation=expected_generation)
    elif expected_hash:
        profile = await persist_query_enrichment(db, pref_id, success, expected_hash=expected_hash)
    else:
        profile = await persist_query_enrichment(db, pref_id, success)
    if profile is None:
        logger.info("Discarded stale profile embedding callback", pref_id=str(pref_id))
        return
    embedded_text = _persisted_embedding_text(profile, state.embedded_text)
    if expected_hash and profile_embedding_content_hash(embedded_text) != expected_hash:
        logger.info("Discarded profile embedding with changed semantic text", pref_id=str(pref_id))
        return
    user_skills = load_user_skills_from_profile(profile)
    profile.is_enrichment_complete = True
    await upsert_profile_point(profile, success, embedded_text=embedded_text)
    outbox = context.require_outbox()
    if state.action == _PrefAction.UPDATE:
        await publish_profile_updated_event(db, outbox, profile, user_skills=user_skills)
    else:
        await publish_profile_created_event(db, outbox, profile, user_skills=user_skills)
    logger.info(
        "Enrichment complete -- lifecycle event published",
        pref_id=str(pref_id),
        action=state.action,
        skill_count=len(user_skills),
    )

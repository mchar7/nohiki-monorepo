"""Command handlers for user-pref-service - handles user commands via Kafka."""

from __future__ import annotations

from uuid import UUID

from nohiki.user.pref.v1 import (
    PrefAttachUploadRequested,
    PrefCreateRequested,
    PrefDeleteRequested,
    PrefDetachUploadRequested,
    PrefFeatureImportanceUpdateRequested,
    PrefUpdateRequested,
    UserPrefSettingsUpdateRequested,
)
from nohiki_fastapi_utils.errors import NotFoundError
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from user_pref_service.core.config import get_settings
from user_pref_service.core.embedding import build_profile_embedding_text, profile_embedding_content_hash
from user_pref_service.core.kafka import kafka_client
from user_pref_service.core.saga_policy import NewEnrichmentSaga
from user_pref_service.db.models import PrefEnrichmentAction, SearchPref
from user_pref_service.events.publishers import (
    publish_profile_deleted_event,
    publish_profile_updated_event,
    publish_settings_created_event,
    publish_settings_updated_event,
)
from user_pref_service.services import profile_service, saga_service, settings_service

logger = get_logger(__name__)
settings = get_settings()

USER_DOES_NOT_OWN_PROFILE = "User does not own profile"
command_group_id = f"{settings.kafka.consumer_group}-commands"


def _persist_embedding_identity(profile: SearchPref, embedding_text: str) -> str:
    """Persist and return the hash for a profile's exact embedding text."""
    if not isinstance(embedding_text, str):
        return ""
    content_hash = profile_embedding_content_hash(embedding_text)
    profile.semantic_content_hash = content_hash
    return content_hash


def _profile_embedding_text(profile: SearchPref) -> str:
    """Use the persisted profile builder, with a typed fallback for legacy doubles."""
    text = profile_service.build_profile_embedding_text_from_profile(profile)
    if isinstance(text, str):
        return text
    name = profile.pref_name if isinstance(getattr(profile, "pref_name", None), str) else ""
    keywords = profile.search_keywords if isinstance(getattr(profile, "search_keywords", None), list) else []
    data = getattr(profile, "user_skills_data", None)
    names = (
        [item["skill_name"] for item in data if isinstance(item, dict) and isinstance(item.get("skill_name"), str)]
        if isinstance(data, list)
        else []
    )
    return build_profile_embedding_text(name, keywords, names)


def _collect_canonical_skill_ids(message: PrefCreateRequested | PrefUpdateRequested) -> list[str]:
    """Collect canonical skill IDs in first-seen order."""
    return list(
        dict.fromkeys(
            (
                *(message.user_skills or []),
                *(message.required_skills or []),
                *(message.preferred_skills or []),
            )
        )
    )


async def _start_enrichment_saga(
    context: MessageContext,
    *,
    profile: SearchPref,
    message: PrefCreateRequested | PrefUpdateRequested,
    action: PrefEnrichmentAction,
    canonical_skill_ids: list[str],
) -> None:
    """Persist the current workflow identity before dispatching enrichment."""
    db = context.require_db_session()
    outbox = context.require_outbox()
    embedding_text = _profile_embedding_text(profile)
    semantic_hash = _persist_embedding_identity(profile, embedding_text)
    profile.enrichment_terminal_status = None
    await db.flush()
    saga = await saga_service.create_enrichment_saga(
        db,
        NewEnrichmentSaga(
            pref_id=profile.id,
            user_id=UUID(message.user_id),
            request_id=UUID(message.request_id),
            correlation_id=(message.metadata.correlation_id if message.metadata else None) or message.request_id,
            action=action,
            raw_skills=canonical_skill_ids,
            semantic_generation=profile.semantic_content_generation,
            semantic_hash=semantic_hash,
        ),
    )
    await saga_service.dispatch_next_step(db, outbox, saga)


@kafka_client.message_handler(Topics.USER_PREF_CREATE_REQUESTED, PrefCreateRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_create_requested(message: PrefCreateRequested, context: MessageContext) -> None:
    """Create a profile and one durable enrichment workflow per request."""
    user_id = UUID(message.user_id)
    request_id = UUID(message.request_id)
    if not message.work_arrangements:
        logger.warning(
            "Rejecting pref create without work arrangements",
            request_id=message.request_id,
            user_id=str(user_id),
        )
        return
    db = context.require_db_session()
    if await saga_service.get_saga_by_request_id(db, request_id) is not None:
        logger.info("Command already processed", request_id=message.request_id)
        return
    profile = await profile_service.get_profile_by_request_id(db, request_id)
    if profile is None:
        profile = await profile_service.create_profile(db, user_id, message)
    await _start_enrichment_saga(
        context,
        profile=profile,
        message=message,
        action=PrefEnrichmentAction.CREATE,
        canonical_skill_ids=_collect_canonical_skill_ids(message),
    )
    logger.info("Pref create enrichment started", request_id=message.request_id, pref_id=str(profile.id))


@kafka_client.message_handler(Topics.USER_PREF_UPDATE_REQUESTED, PrefUpdateRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_update_requested(message: PrefUpdateRequested, context: MessageContext) -> None:
    """Update a profile and supersede any older in-flight enrichment."""
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)
    request_id = UUID(message.request_id)
    db = context.require_db_session()
    if await saga_service.get_saga_by_request_id(db, request_id) is not None:
        logger.info("Command already processed", request_id=message.request_id)
        return
    try:
        profile = await profile_service.get_profile_by_id_for_update(db, pref_id)
    except NotFoundError:
        logger.warning("Profile not found for update, skipping stale event", pref_id=str(pref_id))
        return
    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return
    if await saga_service.get_saga_by_request_id(db, request_id) is not None:
        logger.info("Command already processed after profile lock", request_id=message.request_id)
        return
    outbox = context.require_outbox()
    await saga_service.cancel_pending_enrichment(
        db,
        outbox,
        pref_id,
        message="Preference enrichment superseded by a newer update",
    )
    profile = await profile_service.update_profile(db, pref_id, message)
    updated_fields = getattr(message, "updated_fields", ())
    if not isinstance(updated_fields, (list, tuple, set, frozenset)):
        updated_fields = ()
    skill_fields_updated = bool(set(updated_fields) & {"user_skills", "required_skills", "preferred_skills"})
    await _start_enrichment_saga(
        context,
        profile=profile,
        message=message,
        action=PrefEnrichmentAction.UPDATE,
        canonical_skill_ids=_collect_canonical_skill_ids(message) if skill_fields_updated else [],
    )
    logger.info("Pref update enrichment started", request_id=message.request_id, pref_id=str(pref_id))


@kafka_client.message_handler(Topics.USER_PREF_DELETE_REQUESTED, PrefDeleteRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_delete_requested(message: PrefDeleteRequested, context: MessageContext) -> None:
    """Cancel enrichment and commit profile deletion before Qdrant projection."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)
    db = context.require_db_session()
    profile = await profile_service.get_profile_by_id_optional(db, pref_id)
    if profile is None:
        logger.info("Profile already deleted (idempotent)", pref_id=str(pref_id))
        return
    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return
    outbox = context.require_outbox()
    await saga_service.cancel_pending_enrichment(
        db,
        outbox,
        pref_id,
        message="Profile deleted while preference enrichment was in flight",
    )
    await profile_service.delete_profile(db, pref_id)
    await publish_profile_deleted_event(db, outbox, pref_id, user_id)
    logger.info("Pref delete command completed", request_id=request_id, pref_id=str(pref_id))


@kafka_client.message_handler(
    Topics.USER_PREF_ATTACH_UPLOAD_REQUESTED,
    PrefAttachUploadRequested,
    group_id=command_group_id,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_attach_upload_requested(message: PrefAttachUploadRequested, context: MessageContext) -> None:
    """Handle attachment association command."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)
    upload_id = UUID(message.upload_id)
    upload_type = "example" if message.upload_category in (1, 2) else "additional_context"

    logger.info(
        "Processing attach upload command",
        request_id=request_id,
        pref_id=str(pref_id),
        upload_id=str(upload_id),
    )

    db = context.require_db_session()
    try:
        profile = await profile_service.get_profile_by_id(db, pref_id)
    except NotFoundError:
        logger.warning("Profile not found for attach upload, skipping stale event", pref_id=str(pref_id))
        return
    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return

    await profile_service.associate_attachment(db, pref_id, upload_id, upload_type)

    profile = await profile_service.get_profile_by_id(db, pref_id)
    await publish_profile_updated_event(db, context.require_outbox(), profile)

    logger.info("Attach upload command completed", request_id=request_id)


@kafka_client.message_handler(
    Topics.USER_PREF_DETACH_UPLOAD_REQUESTED,
    PrefDetachUploadRequested,
    group_id=command_group_id,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_detach_upload_requested(message: PrefDetachUploadRequested, context: MessageContext) -> None:
    """Handle attachment disassociation command."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)
    upload_id = UUID(message.upload_id)

    logger.info(
        "Processing detach upload command",
        request_id=request_id,
        pref_id=str(pref_id),
        upload_id=str(upload_id),
    )

    db = context.require_db_session()
    try:
        profile = await profile_service.get_profile_by_id(db, pref_id)
    except NotFoundError:
        logger.warning("Profile not found for detach upload, skipping stale event", pref_id=str(pref_id))
        return
    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return

    await profile_service.disassociate_attachment(db, pref_id, upload_id)

    profile = await profile_service.get_profile_by_id(db, pref_id)
    await publish_profile_updated_event(db, context.require_outbox(), profile)

    logger.info("Detach upload command completed", request_id=request_id)


@kafka_client.message_handler(
    Topics.USER_PREF_SETTINGS_UPDATE_REQUESTED,
    UserPrefSettingsUpdateRequested,
    group_id=command_group_id,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_user_pref_settings_update_requested(
    message: UserPrefSettingsUpdateRequested,
    context: MessageContext,
) -> None:
    """Handle user pref settings update command - upserts user-level settings."""
    user_id = UUID(message.user_id)
    if not message.updated_fields:
        msg = "UserPrefSettingsUpdateRequested.updated_fields is required but was empty"
        raise ValueError(msg)

    logger.info(
        "Processing user pref settings update command",
        request_id=message.request_id,
        user_id=str(user_id),
    )

    db = context.require_db_session()
    user_settings, is_new = await settings_service.upsert_user_settings(db, user_id, message)

    outbox = context.require_outbox()
    if is_new:
        await publish_settings_created_event(db, outbox, user_settings)
    else:
        await publish_settings_updated_event(db, outbox, user_settings)

    logger.info(
        "User pref settings update command completed",
        request_id=message.request_id,
        user_id=str(user_id),
        is_new=is_new,
    )


@kafka_client.message_handler(
    Topics.USER_PREF_FEATURE_IMPORTANCE_UPDATE_REQUESTED,
    PrefFeatureImportanceUpdateRequested,
    group_id=command_group_id,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_feature_importance_update_requested(
    message: PrefFeatureImportanceUpdateRequested,
    context: MessageContext,
) -> None:
    """Handle per-pref feature importance update command."""
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)

    logger.info(
        "Processing pref feature importance update command",
        request_id=message.request_id,
        pref_id=str(pref_id),
    )

    db = context.require_db_session()
    profile = await profile_service.get_profile_by_id(db, pref_id)
    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return

    profile = await settings_service.update_profile_feature_importance(db, pref_id, message)
    await publish_profile_updated_event(db, context.require_outbox(), profile)

    logger.info(
        "Pref feature importance update command completed",
        request_id=message.request_id,
        pref_id=str(pref_id),
    )

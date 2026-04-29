"""Command handlers for user-pref-service - handles user commands via Kafka."""

from __future__ import annotations

from uuid import UUID

from nohiki.ml.v1 import EntityType
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
    publish_profile_deleted_event,
    publish_profile_updated_event,
    publish_settings_created_event,
    publish_settings_updated_event,
)
from user_pref_service.services import profile_service, settings_service
from user_pref_service.services.profile_vector_service import delete_profile_points
from user_pref_service.services.skill_integration import request_skill_normalization

logger = get_logger(__name__)
settings = get_settings()

USER_DOES_NOT_OWN_PROFILE = "User does not own profile"
command_group_id = f"{settings.kafka.consumer_group}-commands"


def _semantic_state_kwargs(profile: SearchPref) -> dict[str, int]:
    """Return callback identity only when persisted profile metadata is available."""
    generation = getattr(profile, "semantic_content_generation", 0)
    if not isinstance(generation, int) or generation <= 0:
        return {}
    return {"semantic_generation": generation}


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


async def _request_profile_embedding(
    pref_id: str,
    embedding_text: str,
    *,
    action: str,
    semantic_generation: int = 0,
    semantic_hash: str = "",
) -> None:
    """Publish a fire-and-forget profile query embedding request."""
    state = PrefEmbeddingState(
        pref_id=pref_id,
        action=action,
        embedded_text=embedding_text if not semantic_hash else "",
        semantic_generation=semantic_generation,
        semantic_hash=semantic_hash,
    )
    operation_id = await get_embedding_publisher().request_embedding(
        text=embedding_text,
        entity_id=pref_id,
        entity_type=EntityType.PROFILE,
        spec=PREF_EMBEDDING_SPEC,
        context=CommandContext(caller_context=state.to_bytes()),
    )
    logger.info(
        "Profile query embedding requested",
        pref_id=pref_id,
        action=action,
        operation_id=operation_id,
    )


@kafka_client.message_handler(Topics.USER_PREF_CREATE_REQUESTED, PrefCreateRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_create_requested(message: PrefCreateRequested, context: MessageContext) -> None:
    """Handle profile create command with completion-aware idempotency."""
    user_id = UUID(message.user_id)
    correlation_id = (message.metadata.correlation_id if message.metadata else None) or message.request_id

    if not message.work_arrangements:
        logger.warning(
            "Rejecting pref create without work arrangements",
            request_id=message.request_id,
            user_id=str(user_id),
        )
        return

    logger.info(
        "Processing pref create command",
        request_id=message.request_id,
        user_id=str(user_id),
    )

    db = context.require_db_session()
    if existing := await profile_service.get_profile_by_request_id(db, UUID(message.request_id)):
        current_version = get_manifest().get_entity_version(EntityType.PROFILE)
        if existing.is_enrichment_complete and (
            existing.collection_version in (None, current_version) or not isinstance(existing.collection_version, str)
        ):
            logger.info("Command already fully processed", request_id=message.request_id)
            return
        profile = existing
    else:
        profile = await profile_service.create_profile(db, user_id, message)

    canonical_skill_ids = _collect_canonical_skill_ids(message)
    if canonical_skill_ids:
        semantic_generation = _semantic_state_kwargs(profile).get("semantic_generation")
        if semantic_generation is None:
            await request_skill_normalization(
                canonical_skill_ids=canonical_skill_ids,
                profile_id=profile.id,
                correlation_id=correlation_id,
                action="create",
            )
        else:
            await request_skill_normalization(
                canonical_skill_ids=canonical_skill_ids,
                profile_id=profile.id,
                correlation_id=correlation_id,
                action="create",
                semantic_generation=semantic_generation,
            )
    else:
        embedding_text = _profile_embedding_text(profile)
        semantic_hash = _persist_embedding_identity(profile, embedding_text)
        await db.flush()
        semantic_generation = _semantic_state_kwargs(profile).get("semantic_generation")
        if semantic_generation is None:
            await _request_profile_embedding(str(profile.id), embedding_text, action="create")
        else:
            await _request_profile_embedding(
                str(profile.id),
                embedding_text,
                action="create",
                semantic_generation=semantic_generation,
                semantic_hash=semantic_hash,
            )

    logger.info(
        "Pref create command completed",
        request_id=message.request_id,
        pref_id=str(profile.id),
    )


@kafka_client.message_handler(Topics.USER_PREF_UPDATE_REQUESTED, PrefUpdateRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_update_requested(message: PrefUpdateRequested, context: MessageContext) -> None:
    """Handle profile update command with the unified enrichment pattern."""
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)
    correlation_id = (message.metadata.correlation_id if message.metadata else None) or message.request_id

    logger.info(
        "Processing pref update command",
        request_id=message.request_id,
        pref_id=str(pref_id),
    )

    db = context.require_db_session()
    try:
        profile = await profile_service.get_profile_by_id(db, pref_id)
    except NotFoundError:
        logger.warning("Profile not found for update, skipping stale event", pref_id=str(pref_id))
        return
    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return

    profile = await profile_service.update_profile(db, pref_id, message)
    profile.is_enrichment_complete = False
    skill_fields = getattr(message, "updated_fields", ())
    if not isinstance(skill_fields, (list, tuple, set, frozenset)):
        skill_fields = (
            ("user_skills", "required_skills", "preferred_skills") if _collect_canonical_skill_ids(message) else ()
        )
    skill_fields_updated = bool(set(skill_fields) & {"user_skills", "required_skills", "preferred_skills"})
    canonical_skill_ids = _collect_canonical_skill_ids(message) if skill_fields_updated else []
    if skill_fields_updated:
        semantic_generation = _semantic_state_kwargs(profile).get("semantic_generation")
        if semantic_generation is None:
            await request_skill_normalization(
                canonical_skill_ids=canonical_skill_ids,
                profile_id=profile.id,
                correlation_id=correlation_id,
                action="update",
            )
        else:
            await request_skill_normalization(
                canonical_skill_ids=canonical_skill_ids,
                profile_id=profile.id,
                correlation_id=correlation_id,
                action="update",
                semantic_generation=semantic_generation,
            )
    else:
        embedding_text = _profile_embedding_text(profile)
        semantic_hash = _persist_embedding_identity(profile, embedding_text)
        await db.flush()
        semantic_generation = _semantic_state_kwargs(profile).get("semantic_generation")
        if semantic_generation is None:
            await _request_profile_embedding(str(profile.id), embedding_text, action="update")
        else:
            await _request_profile_embedding(
                str(profile.id),
                embedding_text,
                action="update",
                semantic_generation=semantic_generation,
                semantic_hash=semantic_hash,
            )
    logger.info(
        "Pref update command completed",
        request_id=message.request_id,
        pref_id=str(pref_id),
    )


@kafka_client.message_handler(Topics.USER_PREF_DELETE_REQUESTED, PrefDeleteRequested, group_id=command_group_id)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_delete_requested(message: PrefDeleteRequested, context: MessageContext) -> None:
    """Handle profile delete command - performs authoritative write (idempotent)."""
    request_id = message.request_id
    user_id = UUID(message.user_id)
    pref_id = UUID(message.pref_id)

    logger.info("Processing pref delete command", request_id=request_id, pref_id=str(pref_id))

    db = context.require_db_session()
    profile = await profile_service.get_profile_by_id_optional(db, pref_id)
    if profile is None:
        logger.info("Profile already deleted (idempotent)", pref_id=str(pref_id))
        return

    if profile.user_id != user_id:
        logger.warning(USER_DOES_NOT_OWN_PROFILE, user_id=str(user_id), pref_id=str(pref_id))
        return

    await delete_profile_points([pref_id])
    await profile_service.delete_profile(db, pref_id)
    await publish_profile_deleted_event(db, context.require_outbox(), pref_id, user_id)

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

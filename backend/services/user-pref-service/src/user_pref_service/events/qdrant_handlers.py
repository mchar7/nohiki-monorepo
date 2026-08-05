"""Project committed preference lifecycle facts into Qdrant."""

from __future__ import annotations

from uuid import UUID

from nohiki.user.pref.v1 import PrefCreated, PrefDeleted, PrefUpdated
from nohiki_kafka_client import MessageContext, Topics

from user_pref_service.core.config import get_settings
from user_pref_service.core.kafka import kafka_client
from user_pref_service.services import profile_service
from user_pref_service.services.profile_vector_service import delete_profile_points, upsert_profile_point

settings = get_settings()


async def _project_current_profile(message: PrefCreated | PrefUpdated, context: MessageContext) -> None:
    """Project current owned state rather than the lifecycle event snapshot."""
    if not message.pref_id:
        msg = f"{type(message).__name__}.pref_id is required but was empty"
        raise ValueError(msg)

    pref_id = UUID(message.pref_id)
    profile = await profile_service.get_profile_by_id_optional(context.require_db_session(), pref_id)
    if profile is None or not profile.is_active:
        await delete_profile_points([pref_id])
        return

    if profile.enrichment_terminal_status is not None:
        return

    await upsert_profile_point(profile)


@kafka_client.message_handler(
    Topics.USER_PREF_CREATED,
    PrefCreated,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_created(message: PrefCreated, context: MessageContext) -> None:
    """Upsert the committed profile's current persisted searchable state."""
    await _project_current_profile(message, context)


@kafka_client.message_handler(
    Topics.USER_PREF_UPDATED,
    PrefUpdated,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_pref_updated(message: PrefUpdated, context: MessageContext) -> None:
    """Upsert the committed profile's current persisted searchable state."""
    await _project_current_profile(message, context)


@kafka_client.message_handler(
    Topics.USER_PREF_DELETED,
    PrefDeleted,
    group_id=settings.kafka.consumer_group,
)
async def handle_pref_deleted(message: PrefDeleted, _context: MessageContext) -> None:
    """Delete the stable profile point after its deletion fact commits."""
    if not message.pref_id:
        msg = "PrefDeleted.pref_id is required but was empty"
        raise ValueError(msg)
    await delete_profile_points([UUID(message.pref_id)])

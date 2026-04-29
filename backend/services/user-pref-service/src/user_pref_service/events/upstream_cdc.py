"""Kafka event handlers for user-pref-service - consumed events from other services."""

from __future__ import annotations

from uuid import UUID

from nohiki.user.auth.v1 import AccountDeleted
from nohiki.user.upload.v1 import UploadDeleted
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from user_pref_service.core.config import get_settings
from user_pref_service.core.kafka import kafka_client
from user_pref_service.events.publishers import publish_profile_updated_batch
from user_pref_service.services import profile_service, settings_service
from user_pref_service.services.profile_vector_service import delete_profile_points

logger = get_logger(__name__)
settings = get_settings()


@kafka_client.message_handler(
    Topics.USER_UPLOAD_DELETED,
    UploadDeleted,
    group_id=settings.kafka.consumer_group,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_attachment_deleted(message: UploadDeleted, context: MessageContext) -> None:
    """Remove attachment references from all profiles when an upload is deleted."""
    if not message.upload_id:
        msg = "UploadDeleted.upload_id is required but was empty"
        raise ValueError(msg)

    upload_id = UUID(message.upload_id)
    logger.info("Processing upload deletion for profiles", upload_id=str(upload_id))

    db = context.require_db_session()
    outbox = context.require_outbox()

    # Fetch affected profiles BEFORE deleting junction rows (ECST compliance)
    affected_profiles = await profile_service.get_profiles_with_attachment(db, upload_id)
    count = await profile_service.remove_attachment_from_all_profiles(db, upload_id)
    refreshed_profiles = await profile_service.get_profiles_by_ids(db, {profile.id for profile in affected_profiles})

    # Publish PrefUpdated for each affected profile so downstream ECST consumers
    # see the updated attachment list in the snapshot.
    await publish_profile_updated_batch(db, outbox, refreshed_profiles)

    logger.info("Removed upload references from profiles", upload_id=str(upload_id), count=count)


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCOUNT_DELETED,
    AccountDeleted,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def handle_user_deleted(message: AccountDeleted, context: MessageContext) -> None:
    """Delete all service-owned data for a deleted user."""
    if not message.user_id:
        msg = "AccountDeleted.user_id is required but was empty"
        raise ValueError(msg)

    user_id = UUID(message.user_id)
    logger.info("Processing account deletion", user_id=str(user_id))

    db = context.require_db_session()
    profile_ids = await profile_service.get_profile_ids_for_user(db, user_id)
    await delete_profile_points(profile_ids)
    profile_count = await profile_service.delete_user_profiles(db, user_id)
    settings_count = await settings_service.delete_user_settings(db, user_id)
    logger.info(
        "Deleted data for deleted user",
        user_id=str(user_id),
        profile_count=profile_count,
        settings_count=settings_count,
    )

"""Kafka event handlers for user-entitlement-service."""

from __future__ import annotations

from uuid import UUID

from nohiki.user.auth.v1 import AccountDeleted, AccountUpdated
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from user_entitlement_service.core.config import get_settings
from user_entitlement_service.core.kafka import kafka_client
from user_entitlement_service.events.publishers import publish_entitlements_changed_event
from user_entitlement_service.services.entitlements_service import create_default_entitlements, delete_entitlements

logger = get_logger(__name__)


settings = get_settings()


@kafka_client.message_handler(Topics.USER_AUTH_ACCOUNT_UPDATED, AccountUpdated, group_id=settings.kafka.consumer_group)
@kafka_client.with_db_session(schema=settings.database.schema_name)
async def _handle_account_updated(message: AccountUpdated, context: MessageContext) -> None:
    """Handle account updated events - create default entitlements if not exists.

    AccountUpdated is published on both account creation and updates.
    This handler ensures every account has entitlements (idempotent via IntegrityError handling).
    """
    if not message.user_id:
        msg = "AccountUpdated.user_id is required but was empty"
        raise ValueError(msg)

    user_id = UUID(message.user_id)
    logger.info("Processing account update for entitlements", user_id=str(user_id))

    db = context.require_db_session()
    outbox = context.require_outbox()

    # Savepoint ensures create + outbox write are atomic; partial failure
    # rolls back only the savepoint, keeping the outer transaction intact.
    async with db.begin_nested():
        entitlements = await create_default_entitlements(db, user_id)
        await publish_entitlements_changed_event(db, outbox, entitlements)
    logger.info("Created default entitlements for new user", user_id=str(user_id), tier=entitlements.tier)


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCOUNT_DELETED,
    AccountDeleted,
    group_id=settings.kafka.consumer_group,
)
@kafka_client.with_db_session()
async def _handle_user_deleted(message: AccountDeleted, context: MessageContext) -> None:
    """Handle account deletion by cleaning up entitlements."""
    if not message.user_id:
        msg = "AccountDeleted.user_id is required but was empty"
        raise ValueError(msg)

    user_id = UUID(message.user_id)
    logger.info("Processing user deletion for entitlements", user_id=str(user_id))

    count = await delete_entitlements(context.require_db_session(), user_id)
    logger.info("Deleted entitlements for user", user_id=str(user_id), count=count)


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()

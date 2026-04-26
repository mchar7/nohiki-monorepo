"""Event publishing utilities for user-auth-service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from nohiki.user.auth.v1 import AccessTokenRevoked, AccountDeleted, AccountUpdated
from nohiki.user.auth.v1 import Account as AccountProto
from nohiki_db_utils import OutboxEventParams, OutboxWriter
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from user_auth_service.core.config import get_settings
from user_auth_service.core.kafka import kafka_client

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from user_auth_service.db.models import Account

logger = get_logger(__name__)
settings = get_settings()


def _account_to_snapshot(account: Account) -> AccountProto:
    """Convert SQLAlchemy Account model to proto Account snapshot for ECST."""
    return AccountProto(
        id=str(account.id),
        email=account.email,
        display_name=account.display_name,
        first_name=account.first_name,
        last_name=account.last_name,
        is_active=account.is_active,
        email_verified=account.is_verified,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


async def publish_user_created_event(db: AsyncSession, outbox: OutboxWriter, user: Account) -> None:
    """Publish user created event via transactional outbox.

    Args:
        db: Database session (must be within a transaction).
        outbox: OutboxWriter instance.
        user: The created user.

    """
    event = AccountUpdated(
        metadata=create_event_metadata(settings.service_name, str(user.id)),
        user_id=str(user.id),
        account_snapshot=_account_to_snapshot(user),
    )

    payload = kafka_client.serialize(Topics.USER_AUTH_ACCOUNT_UPDATED, event)

    await outbox.write_event_raw(
        db=db,
        params=OutboxEventParams(
            aggregate_type="user",
            aggregate_id=str(user.id),
            event_type=Topics.USER_AUTH_ACCOUNT_UPDATED,
            correlation_id=str(user.id),
        ),
        payload=payload,
    )

    logger.debug("Wrote user created event to outbox", user_id=str(user.id))


async def publish_user_updated_event(db: AsyncSession, outbox: OutboxWriter, user: Account) -> None:
    """Publish user updated event via transactional outbox.

    Args:
        db: Database session (must be within a transaction).
        outbox: OutboxWriter instance.
        user: The updated user.

    """
    event = AccountUpdated(
        metadata=create_event_metadata(settings.service_name, str(user.id)),
        user_id=str(user.id),
        account_snapshot=_account_to_snapshot(user),
    )

    payload = kafka_client.serialize(Topics.USER_AUTH_ACCOUNT_UPDATED, event)

    await outbox.write_event_raw(
        db=db,
        params=OutboxEventParams(
            aggregate_type="user",
            aggregate_id=str(user.id),
            event_type=Topics.USER_AUTH_ACCOUNT_UPDATED,
            correlation_id=str(user.id),
        ),
        payload=payload,
    )

    logger.debug("Wrote user updated event to outbox", user_id=str(user.id))


async def publish_user_deleted_event(db: AsyncSession, outbox: OutboxWriter, user_id: uuid.UUID) -> None:
    """Publish user deleted event via transactional outbox.

    Args:
        db: Database session (must be within a transaction).
        outbox: OutboxWriter instance.
        user_id: The deleted user's ID.

    """
    event = AccountDeleted(
        metadata=create_event_metadata(settings.service_name, str(user_id)),
        user_id=str(user_id),
    )

    payload = kafka_client.serialize(Topics.USER_AUTH_ACCOUNT_DELETED, event)

    await outbox.write_event_raw(
        db=db,
        params=OutboxEventParams(
            aggregate_type="user",
            aggregate_id=str(user_id),
            event_type=Topics.USER_AUTH_ACCOUNT_DELETED,
            correlation_id=str(user_id),
        ),
        payload=payload,
    )

    logger.debug("Wrote user deleted event to outbox", user_id=str(user_id))


async def publish_access_token_revoked_event(  # noqa: PLR0913 - transactional publisher boundary
    db: AsyncSession,
    outbox: OutboxWriter,
    *,
    user_id: uuid.UUID,
    jti: uuid.UUID | None,
    expires_at: datetime,
    session_family_id: uuid.UUID | None = None,
) -> None:
    """Write an access-token or session-family revocation fact to the transactional outbox."""
    event = AccessTokenRevoked(
        metadata=create_event_metadata(settings.service_name, str(user_id)),
        user_id=str(user_id),
        expires_at=expires_at,
        session_family_id=str(session_family_id) if session_family_id is not None else None,
    )
    if jti is not None:
        event.jti = str(jti)
    payload = kafka_client.serialize(Topics.USER_AUTH_ACCESS_TOKEN_REVOKED, event)

    await outbox.write_event_raw(
        db=db,
        params=OutboxEventParams(
            aggregate_type="user",
            aggregate_id=str(user_id),
            event_type=Topics.USER_AUTH_ACCESS_TOKEN_REVOKED,
            correlation_id=str(jti or session_family_id or user_id),
        ),
        payload=payload,
    )

    logger.debug(
        "Wrote access token revoked event to outbox",
        user_id=str(user_id),
        jti=str(jti) if jti is not None else None,
        session_family_id=str(session_family_id) if session_family_id is not None else None,
    )

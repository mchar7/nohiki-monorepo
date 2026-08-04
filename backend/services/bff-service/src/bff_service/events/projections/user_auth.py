"""User auth domain projection handlers."""

from __future__ import annotations

from uuid import UUID

from nohiki.user.auth.v1 import AccessTokenRevoked, AccountDeleted, AccountUpdated
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.core.kafka import kafka_client
from bff_service.db.models import AccountProjection, UserRevocationCutoff
from bff_service.events.projections._constants import (
    projection_auth_revocation_group_id,
    projection_priority_group_id,
)
from bff_service.services.auth_revocation import (
    record_access_token_revocation,
    record_session_family_revocation,
    record_user_revocation_cutoff,
)

logger = get_logger(__name__)


async def _lock_account_lifecycle(session: AsyncSession, user_id: UUID) -> None:
    """Serialize account update/delete transactions for one permanent user ID."""
    lock_key = user_id.int & ((1 << 63) - 1)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCOUNT_UPDATED,
    AccountUpdated,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_account_updated(message: AccountUpdated, context: MessageContext) -> None:
    """Handle account created/updated events - upsert projection from ECST snapshot."""
    snapshot = message.account_snapshot
    if snapshot is None:
        logger.warning("AccountUpdated missing account_snapshot (pre-ECST event), skipping", user_id=message.user_id)
        return

    new_id = UUID(snapshot.id)
    session = context.require_db_session()
    await _lock_account_lifecycle(session, new_id)
    if await session.scalar(
        select(UserRevocationCutoff.user_id).where(
            UserRevocationCutoff.user_id == new_id,
            UserRevocationCutoff.is_permanent.is_(True),
        )
    ):
        logger.info("Ignoring account update for permanently deleted user", user_id=snapshot.id)
        return

    if not snapshot.is_active:
        metadata = message.metadata
        if metadata is None:
            msg = "Inactive AccountUpdated metadata is required for revocation cutoff"
            raise ValueError(msg)
        await record_user_revocation_cutoff(
            session,
            user_id=new_id,
            revoked_before=metadata.timestamp,
            is_permanent=False,
        )

    # Take a row-level lock on any stale account holding this email so two
    # concurrent updaters serialise on the same row instead of racing the
    # delete/insert pair against the UNIQUE(email) constraint.
    await session.execute(
        select(AccountProjection.id)
        .where(AccountProjection.email == snapshot.email, AccountProjection.id != new_id)
        .with_for_update()
    )
    await session.execute(
        delete(AccountProjection).where(
            AccountProjection.email == snapshot.email,
            AccountProjection.id != new_id,
        )
    )
    stmt = (
        insert(AccountProjection)
        .values(
            id=new_id,
            email=snapshot.email,
            display_name=snapshot.display_name,
            first_name=snapshot.first_name,
            last_name=snapshot.last_name,
            is_active=snapshot.is_active,
            email_verified=snapshot.email_verified,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "email": snapshot.email,
                "display_name": snapshot.display_name,
                "first_name": snapshot.first_name,
                "last_name": snapshot.last_name,
                "is_active": snapshot.is_active,
                "email_verified": snapshot.email_verified,
                "updated_at": snapshot.updated_at,
            },
        )
    )
    await session.execute(stmt)
    logger.info("Account projection upserted", user_id=snapshot.id)


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCESS_TOKEN_REVOKED,
    AccessTokenRevoked,
    group_id=projection_auth_revocation_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_access_token_revoked(message: AccessTokenRevoked, context: MessageContext) -> None:
    """Project access-token and session-family revocations into the durable ledger."""
    session = context.require_db_session()
    user_id = UUID(message.user_id)
    if message.jti:
        await record_access_token_revocation(
            session,
            user_id=user_id,
            jti=message.jti,
            expires_at=message.expires_at,
        )
    if message.session_family_id:
        metadata = message.metadata
        if metadata is None:
            msg = "AccessTokenRevoked metadata is required for family cutoff"
            raise ValueError(msg)
        await record_session_family_revocation(
            session,
            family_id=message.session_family_id,
            user_id=user_id,
            revoked_before=metadata.timestamp,
            expires_at=message.expires_at,
        )
    if not message.jti and not message.session_family_id:
        msg = "AccessTokenRevoked requires a JTI or session family"
        raise ValueError(msg)
    logger.info("Access token revocation projected", user_id=message.user_id)


@kafka_client.message_handler(
    Topics.USER_AUTH_ACCOUNT_DELETED,
    AccountDeleted,
    group_id=projection_auth_revocation_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_account_deleted(message: AccountDeleted, context: MessageContext) -> None:
    """Permanently tombstone the account and remove its mutable projection atomically."""
    metadata = message.metadata
    if metadata is None:
        msg = "AccountDeleted metadata is required for revocation cutoff"
        raise ValueError(msg)
    revoked_before = metadata.timestamp

    session = context.require_db_session()
    user_id = UUID(message.user_id)
    await _lock_account_lifecycle(session, user_id)
    await record_user_revocation_cutoff(
        session,
        user_id=user_id,
        revoked_before=revoked_before,
        is_permanent=True,
    )
    await session.execute(delete(AccountProjection).where(AccountProjection.id == user_id))
    logger.info("Account projection deleted with revocation cutoff", user_id=message.user_id)

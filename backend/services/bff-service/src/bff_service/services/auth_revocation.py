"""Persistence operations for the BFF access-token revocation ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.db.models import RevokedAccessToken, RevokedSessionFamily, UserRevocationCutoff


class JtiCollisionError(ValueError):
    """Raised when a JTI is already owned by a different user."""


async def record_access_token_revocation(
    session: AsyncSession,
    *,
    user_id: UUID,
    jti: str,
    expires_at: datetime,
) -> None:
    """Idempotently retain a JTI, rejecting reuse by another user."""
    token_jti = UUID(jti)
    base = insert(RevokedAccessToken).values(jti=token_jti, user_id=user_id, expires_at=expires_at)
    result = cast(
        "CursorResult[tuple[()]]",
        await session.execute(
            base.on_conflict_do_update(
                index_elements=["jti"],
                set_={"expires_at": sa.func.greatest(RevokedAccessToken.expires_at, base.excluded.expires_at)},
                where=RevokedAccessToken.user_id == base.excluded.user_id,
            )
        ),
    )
    if result.rowcount == 0:
        raise JtiCollisionError


async def record_user_revocation_cutoff(
    session: AsyncSession,
    *,
    user_id: UUID,
    revoked_before: datetime,
    is_permanent: bool,
    expires_at: datetime | None = None,
) -> None:
    """Record a monotonic user-wide cutoff, optionally as a permanent tombstone."""
    retention_horizon = expires_at or datetime.max.replace(tzinfo=UTC)
    base = insert(UserRevocationCutoff).values(
        user_id=user_id,
        revoked_before=revoked_before,
        expires_at=retention_horizon,
        is_permanent=is_permanent,
    )
    await session.execute(
        base.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "revoked_before": sa.func.greatest(UserRevocationCutoff.revoked_before, base.excluded.revoked_before),
                "expires_at": sa.func.greatest(UserRevocationCutoff.expires_at, base.excluded.expires_at),
                "is_permanent": UserRevocationCutoff.is_permanent | base.excluded.is_permanent,
            },
        )
    )


async def record_session_family_revocation(
    session: AsyncSession,
    *,
    family_id: str,
    user_id: UUID,
    revoked_before: datetime,
    expires_at: datetime,
) -> None:
    """Idempotently retain a refresh-family cutoff, rejecting cross-user reuse."""
    family_uuid = UUID(family_id)
    base = insert(RevokedSessionFamily).values(
        family_id=family_uuid,
        user_id=user_id,
        revoked_before=revoked_before,
        expires_at=expires_at,
    )
    result = cast(
        "CursorResult[tuple[()]]",
        await session.execute(
            base.on_conflict_do_update(
                index_elements=["family_id"],
                set_={
                    "revoked_before": sa.func.greatest(
                        RevokedSessionFamily.revoked_before, base.excluded.revoked_before
                    ),
                    "expires_at": sa.func.greatest(RevokedSessionFamily.expires_at, base.excluded.expires_at),
                },
                where=RevokedSessionFamily.user_id == base.excluded.user_id,
            )
        ),
    )
    if result.rowcount == 0:
        raise JtiCollisionError


async def is_access_token_revoked(
    session: AsyncSession,
    *,
    user_id: UUID,
    jti: str,
    issued_at: datetime,
    session_family_id: str | None = None,
) -> bool:
    """Return whether a JTI, permanent tombstone, or family cutoff revokes a token."""
    token_jti = UUID(jti)
    family_uuid = UUID(session_family_id) if session_family_id is not None else None
    now = sa.func.now()
    predicates = [
        sa.exists().where(
            RevokedAccessToken.jti == token_jti,
            RevokedAccessToken.user_id == user_id,
            RevokedAccessToken.expires_at > now,
        ),
        sa.exists().where(
            UserRevocationCutoff.user_id == user_id,
            sa.or_(
                UserRevocationCutoff.is_permanent.is_(True),
                sa.and_(
                    issued_at <= UserRevocationCutoff.revoked_before,
                    UserRevocationCutoff.expires_at > now,
                ),
            ),
        ),
    ]
    if family_uuid is not None:
        predicates.append(
            sa.exists().where(
                RevokedSessionFamily.family_id == family_uuid,
                RevokedSessionFamily.user_id == user_id,
                RevokedSessionFamily.expires_at > now,
                issued_at <= RevokedSessionFamily.revoked_before,
            )
        )
    return bool(await session.scalar(sa.select(sa.or_(*predicates))))


async def delete_expired_revocations(session: AsyncSession) -> int:
    """Delete expired token and family rows; permanent user tombstones remain."""
    now = sa.func.now()
    token_result = cast(
        "CursorResult[tuple[()]]",
        await session.execute(sa.delete(RevokedAccessToken).where(RevokedAccessToken.expires_at <= now)),
    )
    family_result = cast(
        "CursorResult[tuple[()]]",
        await session.execute(sa.delete(RevokedSessionFamily).where(RevokedSessionFamily.expires_at <= now)),
    )
    cutoff_result = cast(
        "CursorResult[tuple[()]]",
        await session.execute(
            sa.delete(UserRevocationCutoff).where(
                UserRevocationCutoff.is_permanent.is_(False),
                UserRevocationCutoff.expires_at <= now,
            )
        ),
    )
    return token_result.rowcount + family_result.rowcount + cutoff_result.rowcount

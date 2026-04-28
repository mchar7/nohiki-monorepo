"""Entitlements service business logic."""

from __future__ import annotations

from uuid import UUID

from nohiki.common.v1 import BillingProvider
from nohiki_common_exceptions import DataNotFoundError
from nohiki_observability import get_logger
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from user_entitlement_service.core.tiers import (
    TierConfig,
    get_default_subscription_status,
    get_default_tier,
    get_tier_config,
)
from user_entitlement_service.db.models import Entitlement

logger = get_logger(__name__)


def _apply_tier_config(entitlements: Entitlement, tier_config: TierConfig) -> None:
    """Apply tier configuration to entitlements model."""
    entitlements.discovery_frequency_limit = tier_config.discovery_frequency_limit
    entitlements.max_prefs = tier_config.max_prefs
    entitlements.max_uploads_per_pref = tier_config.max_uploads_per_pref
    entitlements.allowed_sources = list(tier_config.allowed_sources)
    entitlements.features_enabled = dict(tier_config.features_enabled)


async def get_entitlements_by_user_id(db: AsyncSession, user_id: UUID) -> Entitlement:
    """Get entitlements by user ID.

    Args:
        db: Database session.
        user_id: Account ID.

    Returns:
        Entitlement model.

    Raises:
        NotFoundError: If entitlements not found.

    """
    result = await db.execute(select(Entitlement).where(Entitlement.user_id == user_id))
    entitlements = result.scalar_one_or_none()

    if not entitlements:
        raise DataNotFoundError(resource_type="Entitlement", resource_id=str(user_id))

    return entitlements


async def create_default_entitlements(db: AsyncSession, user_id: UUID) -> Entitlement:
    """Create default (free tier) entitlements for a new user.

    Args:
        db: Database session.
        user_id: Account ID.

    Returns:
        Created Entitlement model.

    Raises:
        IntegrityError: If an integrity constraint other than duplicate user is violated.

    """
    default_tier = get_default_tier()
    default_status = get_default_subscription_status()
    tier_config = get_tier_config(default_tier)

    entitlements = Entitlement(
        user_id=user_id,
        tier=default_tier,
        subscription_status=default_status,
        billing_provider=BillingProvider.NONE,
    )
    _apply_tier_config(entitlements, tier_config)

    db.add(entitlements)

    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        # A duplicate user is idempotent; unrelated constraint failures must retain
        # their original error instead of being disguised as a missing record.
        try:
            existing = await get_entitlements_by_user_id(db, user_id)
        except DataNotFoundError:
            raise exc from None
        logger.warning("Entitlements already exist for user", user_id=str(user_id))
        return existing

    logger.info(
        "Created default entitlements",
        user_id=str(user_id),
        tier=default_tier.name,
    )
    return entitlements


async def delete_entitlements(db: AsyncSession, user_id: UUID) -> int:
    """Delete entitlements for a user.

    Args:
        db: Database session.
        user_id: Account ID.

    Returns:
        Number of deleted records.

    """
    result = await db.execute(delete(Entitlement).where(Entitlement.user_id == user_id))
    count: int = int(getattr(result, "rowcount", 0) or 0)
    await db.flush()

    if count > 0:
        logger.info("Deleted entitlements for user", user_id=str(user_id))

    return count

"""Event publishers for user-entitlement-service."""

from __future__ import annotations

from nohiki.common.v1 import EntitlementSnapshot, SubscriptionTier
from nohiki.user.entitlement.v1 import EntitlementChanged
from nohiki_db_utils import OutboxEventParams, OutboxWriter
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from user_entitlement_service.core.config import get_settings
from user_entitlement_service.db.models import Entitlement

logger = get_logger(__name__)
settings = get_settings()


def _build_entitlement_snapshot(entitlements: Entitlement) -> EntitlementSnapshot:
    features_enabled: dict[str, bool] = {str(k): bool(v) for k, v in (entitlements.features_enabled or {}).items()}

    return EntitlementSnapshot(
        id=str(entitlements.id),
        user_id=str(entitlements.user_id),
        tier=entitlements.tier,
        subscription_status=entitlements.subscription_status,
        discovery_frequency_limit=entitlements.discovery_frequency_limit,
        max_prefs=entitlements.max_prefs,
        max_uploads_per_pref=entitlements.max_uploads_per_pref,
        allowed_sources=list(entitlements.allowed_sources),
        features_enabled=features_enabled,
    )


AGGREGATE_TYPE = "entitlement"


async def publish_entitlements_changed_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    entitlements: Entitlement,
    *,
    previous_tier: SubscriptionTier = SubscriptionTier.FREE,
    change_reason: str = "",
) -> None:
    """Publish entitlement change event via outbox.

    Args:
        db: Database session (must be within a transaction).
        outbox: Outbox writer for CDC pickup.
        entitlements: Current entitlement state to publish.
        previous_tier: Tier before this change (defaults to FREE for initial creation).
        change_reason: Human-readable reason for the change.

    """
    event = EntitlementChanged(
        metadata=create_event_metadata(settings.service_name, str(entitlements.id)),
        user_id=str(entitlements.user_id),
        entitlement_snapshot=_build_entitlement_snapshot(entitlements),
        previous_tier=previous_tier,
        change_reason=change_reason,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(entitlements.user_id),
            event_type=Topics.USER_ENTITLEMENT_CHANGED,
        ),
        event=event,
    )

    logger.info(
        "Published entitlement change event",
        user_id=str(entitlements.user_id),
        tier=entitlements.tier,
    )

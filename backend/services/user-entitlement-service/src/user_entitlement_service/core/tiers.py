"""Tier configuration for entitlements.

Defines the limits and features for each subscription tier.
This is the single source of truth for tier-based feature access.
Uses proto enums as canonical types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nohiki.common.v1 import (
    DiscoveryFrequency,
    JobBoardSource,
    SubscriptionStatus,
    SubscriptionTier,
)


@dataclass(frozen=True)
class TierConfig:
    """Configuration for a subscription tier."""

    # Scraping limits
    discovery_frequency_limit: DiscoveryFrequency
    max_prefs: int
    max_uploads_per_pref: int
    allowed_sources: tuple[JobBoardSource, ...]

    # Feature flags
    features_enabled: dict[str, bool] = field(default_factory=dict)


# Tier configurations - single source of truth
TIER_CONFIGS: dict[SubscriptionTier, TierConfig] = {
    SubscriptionTier.FREE: TierConfig(
        discovery_frequency_limit=DiscoveryFrequency.DAILY,
        max_prefs=1,
        max_uploads_per_pref=3,
        allowed_sources=(JobBoardSource.INDEED,),
        features_enabled={},
    ),
    SubscriptionTier.BASIC: TierConfig(
        discovery_frequency_limit=DiscoveryFrequency.DAILY,
        max_prefs=2,
        max_uploads_per_pref=5,
        allowed_sources=(
            JobBoardSource.INDEED,
            JobBoardSource.LINKEDIN,
        ),
        features_enabled={},
    ),
    SubscriptionTier.PRO: TierConfig(
        discovery_frequency_limit=DiscoveryFrequency.TWICE_DAILY,
        max_prefs=5,
        max_uploads_per_pref=10,
        allowed_sources=(
            JobBoardSource.INDEED,
            JobBoardSource.LINKEDIN,
            JobBoardSource.GLASSDOOR,
        ),
        features_enabled={"auto_tailor": True, "priority_matching": True},
    ),
    SubscriptionTier.ENTERPRISE: TierConfig(
        discovery_frequency_limit=DiscoveryFrequency.HOURLY,
        max_prefs=20,
        max_uploads_per_pref=25,
        allowed_sources=(
            JobBoardSource.INDEED,
            JobBoardSource.LINKEDIN,
            JobBoardSource.GLASSDOOR,
            JobBoardSource.ZIPRECRUITER,
            JobBoardSource.GOOGLE,
        ),
        features_enabled={
            "auto_tailor": True,
            "priority_matching": True,
            "api_access": True,
        },
    ),
}


def get_tier_config(tier: SubscriptionTier) -> TierConfig:
    """Get configuration for a tier."""
    if tier not in TIER_CONFIGS:
        return TIER_CONFIGS[SubscriptionTier.FREE]
    return TIER_CONFIGS[tier]


def get_default_tier() -> SubscriptionTier:
    """Get the default tier for new users."""
    return SubscriptionTier.FREE


def get_default_subscription_status() -> SubscriptionStatus:
    """Get the default subscription status for new users."""
    return SubscriptionStatus.NONE


__all__ = [
    "DiscoveryFrequency",
    "JobBoardSource",
    "SubscriptionStatus",
    "SubscriptionTier",
    "TierConfig",
    "get_default_subscription_status",
    "get_default_tier",
    "get_tier_config",
]

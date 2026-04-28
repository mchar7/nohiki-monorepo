"""Unit tests for entitlements service."""

from __future__ import annotations

from nohiki.common.v1 import (
    DiscoveryFrequency,
    JobBoardSource,
    SubscriptionTier,
)
from user_entitlement_service.core.tiers import (
    TIER_CONFIGS,
    TierConfig,
)


class TestTierConfig:
    """Tests for tier configuration."""

    def test_free_tier_config(self) -> None:
        """Test free tier has correct limits."""
        config = TIER_CONFIGS[SubscriptionTier.FREE]

        assert config.discovery_frequency_limit == DiscoveryFrequency.DAILY
        assert config.max_prefs == 1
        assert config.max_uploads_per_pref == 3
        assert JobBoardSource.INDEED in config.allowed_sources
        assert len(config.features_enabled) == 0

    def test_pro_tier_config(self) -> None:
        """Test pro tier has higher limits than free."""
        free_config = TIER_CONFIGS[SubscriptionTier.FREE]
        pro_config = TIER_CONFIGS[SubscriptionTier.PRO]

        assert pro_config.max_prefs > free_config.max_prefs
        assert pro_config.max_uploads_per_pref > free_config.max_uploads_per_pref
        assert len(pro_config.allowed_sources) > len(free_config.allowed_sources)
        assert pro_config.features_enabled.get("auto_tailor") is True

    def test_enterprise_tier_config(self) -> None:
        """Test enterprise tier has highest limits."""
        pro_config = TIER_CONFIGS[SubscriptionTier.PRO]
        enterprise_config = TIER_CONFIGS[SubscriptionTier.ENTERPRISE]

        assert enterprise_config.max_prefs > pro_config.max_prefs
        assert enterprise_config.max_uploads_per_pref > pro_config.max_uploads_per_pref
        assert enterprise_config.features_enabled.get("api_access") is True

    def test_default_tier_is_free(self) -> None:
        """Test default tier for new users is free."""
        assert SubscriptionTier.FREE in TIER_CONFIGS

    def test_all_tiers_have_configs(self) -> None:
        """Test all tiers have configurations defined."""
        for tier in SubscriptionTier:
            if tier != SubscriptionTier.UNSPECIFIED:
                config = TIER_CONFIGS.get(tier)
                assert config is not None
                assert isinstance(config, TierConfig)

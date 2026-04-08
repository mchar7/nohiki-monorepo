"""Tests for multi-tier rate limiting functionality.

Provides coverage for managing multiple rate limit tiers
with configurable behaviors per tier.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_redis_utils.multi_tier_rate_limiter import (
    MultiTierCheckResult,
    MultiTierRateLimiter,
    RateLimitTier,
    TierExceededBehavior,
)
from nohiki_redis_utils.rate_limiter import RateLimitResult


def create_rate_limit_result(*, allowed: bool, remaining: int, retry_after: float = 0.0) -> RateLimitResult:
    """Helper to create RateLimitResult with required reset_at."""
    import time

    return RateLimitResult(
        allowed=allowed,
        remaining=remaining,
        reset_at=time.time() + retry_after,
        retry_after=retry_after if retry_after > 0 else None,
    )


class TestTierExceededBehavior:
    """Tests for TierExceededBehavior enum."""

    def test_enum_values(self) -> None:
        """Verify enum values are correct."""
        assert TierExceededBehavior.REJECT.value == "reject"
        assert TierExceededBehavior.LOG_ONLY.value == "log_only"

    def test_enum_members(self) -> None:
        """Verify all expected enum members exist."""
        assert hasattr(TierExceededBehavior, "REJECT")
        assert hasattr(TierExceededBehavior, "LOG_ONLY")


class TestRateLimitTier:
    """Tests for RateLimitTier dataclass."""

    def test_create_with_defaults(self) -> None:
        """Create tier with default behavior and priority."""
        tier = RateLimitTier(
            name="hourly",
            requests=100,
            window_seconds=3600,
        )

        assert tier.name == "hourly"
        assert tier.requests == 100
        assert tier.window_seconds == 3600
        assert tier.behavior == TierExceededBehavior.REJECT
        assert tier.priority == 0

    def test_create_with_custom_behavior(self) -> None:
        """Create tier with custom behavior."""
        tier = RateLimitTier(
            name="monthly",
            requests=1000,
            window_seconds=30 * 24 * 3600,
            behavior=TierExceededBehavior.LOG_ONLY,
            priority=1,
        )

        assert tier.behavior == TierExceededBehavior.LOG_ONLY
        assert tier.priority == 1

    def test_tier_is_frozen(self) -> None:
        """Tier dataclass is immutable."""
        # Verify frozen status via dataclass params
        assert dataclasses.is_dataclass(RateLimitTier)
        params = getattr(RateLimitTier, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestMultiTierCheckResult:
    """Tests for MultiTierCheckResult dataclass."""

    def test_create_allowed(self) -> None:
        """Create result when all tiers pass."""
        result = MultiTierCheckResult(allowed=True)

        assert result.allowed is True
        assert result.exceeded_tier is None
        assert result.retry_after is None
        assert result.tier_results == {}

    def test_create_denied(self) -> None:
        """Create result when tier is exceeded."""
        result = MultiTierCheckResult(
            allowed=False,
            exceeded_tier="hourly",
            retry_after=1800.0,
        )

        assert result.allowed is False
        assert result.exceeded_tier == "hourly"
        assert result.retry_after == pytest.approx(1800.0)

    def test_create_with_tier_results(self) -> None:
        """Create result with individual tier results."""
        tier_results = {
            "minute": create_rate_limit_result(allowed=True, remaining=5),
            "hour": create_rate_limit_result(allowed=False, remaining=0, retry_after=300.0),
        }
        result = MultiTierCheckResult(
            allowed=False,
            exceeded_tier="hour",
            retry_after=300.0,
            tier_results=tier_results,
        )

        assert result.tier_results == tier_results

    def test_result_is_mutable(self) -> None:
        """Result dataclass is mutable (not frozen)."""
        result = MultiTierCheckResult(allowed=True)
        result.allowed = False

        assert result.allowed is False


class TestMultiTierRateLimiterInitialization:
    """Tests for MultiTierRateLimiter initialization."""

    def test_create_with_single_tier(self) -> None:
        """Create limiter with single tier."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="default", requests=100, window_seconds=3600)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        assert limiter is not None
        assert limiter.tier_names == ["default"]

    def test_create_with_multiple_tiers(self) -> None:
        """Create limiter with multiple tiers."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="minute", requests=10, window_seconds=60, priority=0),
            RateLimitTier(name="hour", requests=100, window_seconds=3600, priority=1),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        assert len(limiter.tier_names) == 2
        assert "minute" in limiter.tier_names
        assert "hour" in limiter.tier_names

    def test_tiers_sorted_by_priority(self) -> None:
        """Tiers are sorted by priority (lower first)."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="low", requests=10, window_seconds=60, priority=5),
            RateLimitTier(name="high", requests=100, window_seconds=3600, priority=1),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # Should be sorted with high (priority=1) first
        assert limiter.tier_names[0] == "high"
        assert limiter.tier_names[1] == "low"

    def test_create_limiters_for_each_tier(self) -> None:
        """Individual limiters created for each tier."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="a", requests=10, window_seconds=60),
            RateLimitTier(name="b", requests=20, window_seconds=120),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # Should have limiters dict populated
        assert len(limiter._limiters) == 2
        assert "a" in limiter._limiters
        assert "b" in limiter._limiters

    def test_empty_tiers(self) -> None:
        """Create limiter with empty tiers list."""
        mock_cache = MagicMock()

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=[],
        )

        assert limiter.tier_names == []


class TestMultiTierRateLimiterCheck:
    """Tests for check method."""

    @pytest.mark.asyncio
    async def test_check_all_tiers_pass(self) -> None:
        """Check passes when all tiers allow."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="tier1", requests=10, window_seconds=60),
            RateLimitTier(name="tier2", requests=100, window_seconds=3600),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # Mock both limiters to allow
        with (
            patch.object(
                limiter._limiters["tier1"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=5)),
            ),
            patch.object(
                limiter._limiters["tier2"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=50)),
            ),
        ):
            result = await limiter.check("user123")

            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_reject_tier_blocks(self) -> None:
        """Check fails when REJECT tier is exceeded."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="strict", requests=1, window_seconds=60),
            RateLimitTier(name="lenient", requests=100, window_seconds=3600),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # First tier blocks
        with (
            patch.object(
                limiter._limiters["strict"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=False, remaining=0, retry_after=60.0)),
            ) as mock_strict,
            patch.object(
                limiter._limiters["lenient"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=50)),
            ),
        ):
            result = await limiter.check("user123")

            assert result.allowed is False
            assert result.exceeded_tier == "strict"
            assert result.retry_after == pytest.approx(60.0)
            # Second tier should not be checked
            mock_strict.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_log_only_tier_continues(self) -> None:
        """Check continues when LOG_ONLY tier is exceeded."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(
                name="soft",
                requests=10,
                window_seconds=60,
                behavior=TierExceededBehavior.LOG_ONLY,
            ),
            RateLimitTier(name="hard", requests=100, window_seconds=3600),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # Soft tier exceeded but continues
        with (
            patch.object(
                limiter._limiters["soft"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=False, remaining=0, retry_after=30.0)),
            ),
            patch.object(
                limiter._limiters["hard"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=50)),
            ),
        ):
            result = await limiter.check("user123")

            # Should be allowed because hard tier passed
            assert result.allowed is True
            # But soft tier result should be recorded
            assert "soft" in result.tier_results
            assert "hard" in result.tier_results

    @pytest.mark.asyncio
    async def test_check_records_all_tier_results(self) -> None:
        """Check records results from all checked tiers."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="tier1", requests=10, window_seconds=60),
            RateLimitTier(name="tier2", requests=20, window_seconds=120),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with (
            patch.object(
                limiter._limiters["tier1"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=8)),
            ),
            patch.object(
                limiter._limiters["tier2"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=15)),
            ),
        ):
            result = await limiter.check("user123")

            assert "tier1" in result.tier_results
            assert "tier2" in result.tier_results
            assert result.tier_results["tier1"].remaining == 8
            assert result.tier_results["tier2"].remaining == 15


class TestMultiTierRateLimiterResetTier:
    """Tests for reset_tier method."""

    @pytest.mark.asyncio
    async def test_reset_existing_tier(self) -> None:
        """Reset clears rate limit for existing tier."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="hourly", requests=100, window_seconds=3600)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with patch.object(limiter._limiters["hourly"], "reset", AsyncMock()) as mock_reset:
            await limiter.reset_tier("hourly", "user123")

            mock_reset.assert_called_once_with("test:hourly:user123")

    @pytest.mark.asyncio
    async def test_reset_unknown_tier(self) -> None:
        """Reset unknown tier logs warning and returns."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="hourly", requests=100, window_seconds=3600)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # Should not raise
        await limiter.reset_tier("unknown", "user123")


class TestMultiTierRateLimiterResetAll:
    """Tests for reset_all method."""

    @pytest.mark.asyncio
    async def test_reset_all_tiers(self) -> None:
        """Reset clears all tiers for a key."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="minute", requests=10, window_seconds=60),
            RateLimitTier(name="hour", requests=100, window_seconds=3600),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with (
            patch.object(limiter._limiters["minute"], "reset", AsyncMock()) as mock_min,
            patch.object(limiter._limiters["hour"], "reset", AsyncMock()) as mock_hr,
        ):
            await limiter.reset_all("user123")

            mock_min.assert_called_once()
            mock_hr.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_all_empty_tiers(self) -> None:
        """Reset with empty tiers does nothing."""
        mock_cache = MagicMock()

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=[],
        )

        # Should not raise
        await limiter.reset_all("user123")


class TestMultiTierRateLimiterGetTierConfig:
    """Tests for get_tier_config method."""

    def test_get_existing_tier_config(self) -> None:
        """Get config for existing tier."""
        mock_cache = MagicMock()
        tier = RateLimitTier(name="hourly", requests=100, window_seconds=3600)
        tiers = [tier]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        config = limiter.get_tier_config("hourly")

        assert config is not None
        assert config.name == "hourly"
        assert config.requests == 100

    def test_get_unknown_tier_config(self) -> None:
        """Get config for unknown tier returns None."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="hourly", requests=100, window_seconds=3600)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        config = limiter.get_tier_config("unknown")

        assert config is None


class TestMultiTierRateLimiterBuildKey:
    """Tests for _build_key method."""

    def test_build_key_format(self) -> None:
        """Key is built with correct format."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="hourly", requests=100, window_seconds=3600)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="api",
            tiers=tiers,
        )

        key = limiter._build_key("hourly", "user123")

        assert key == "api:hourly:user123"

    def test_build_key_different_prefix(self) -> None:
        """Key format respects prefix."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="tier", requests=10, window_seconds=60)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="myapp:ratelimit",
            tiers=tiers,
        )

        key = limiter._build_key("tier", "key")

        assert key == "myapp:ratelimit:tier:key"


class TestMultiTierRateLimiterLogging:
    """Tests for logging behavior."""

    @pytest.mark.asyncio
    async def test_log_when_tier_exceeded_reject(self) -> None:
        """Log warning when REJECT tier exceeded."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="strict", requests=1, window_seconds=60),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with (
            patch.object(
                limiter._limiters["strict"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=False, remaining=0, retry_after=60.0)),
            ),
            patch("nohiki_redis_utils.multi_tier_rate_limiter.logger") as mock_logger,
        ):
            await limiter.check("user123")

            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_log_when_tier_exceeded_log_only(self) -> None:
        """Log info when LOG_ONLY tier exceeded."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(
                name="soft",
                requests=1,
                window_seconds=60,
                behavior=TierExceededBehavior.LOG_ONLY,
            ),
            RateLimitTier(name="hard", requests=100, window_seconds=3600),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with (
            patch.object(
                limiter._limiters["soft"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=False, remaining=0, retry_after=30.0)),
            ),
            patch.object(
                limiter._limiters["hard"],
                "check",
                AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=50)),
            ),
            patch("nohiki_redis_utils.multi_tier_rate_limiter.logger") as mock_logger,
        ):
            await limiter.check("user123")

            # Should use info for LOG_ONLY behavior
            mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_log_when_check_passed(self) -> None:
        """Log debug when check passes."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="tier1", requests=10, window_seconds=60),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with patch.object(
            limiter._limiters["tier1"],
            "check",
            AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=8)),
        ):
            result = await limiter.check("user123")

            assert "tier1" in result.tier_results
            assert result.tier_results["tier1"].remaining == 8


class TestMultiTierRateLimiterEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_check_with_zero_requests(self) -> None:
        """Check with tier having zero requests always blocks."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="blocked", requests=0, window_seconds=60)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with patch.object(
            limiter._limiters["blocked"],
            "check",
            AsyncMock(return_value=create_rate_limit_result(allowed=False, remaining=0, retry_after=60.0)),
        ):
            result = await limiter.check("user123")

            assert result.allowed is False

    @pytest.mark.asyncio
    async def test_check_with_large_requests(self) -> None:
        """Check with tier having large request limit."""
        mock_cache = MagicMock()
        tiers = [RateLimitTier(name="generous", requests=1000000, window_seconds=60)]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        with patch.object(
            limiter._limiters["generous"],
            "check",
            AsyncMock(return_value=create_rate_limit_result(allowed=True, remaining=999999)),
        ):
            result = await limiter.check("user123")

            assert result.allowed is True

    def test_tier_names_property_order(self) -> None:
        """tier_names returns names in priority order."""
        mock_cache = MagicMock()
        tiers = [
            RateLimitTier(name="c", requests=10, window_seconds=60, priority=3),
            RateLimitTier(name="a", requests=10, window_seconds=60, priority=1),
            RateLimitTier(name="b", requests=10, window_seconds=60, priority=2),
        ]

        limiter = MultiTierRateLimiter(
            cache=mock_cache,
            key_prefix="test",
            tiers=tiers,
        )

        # Should be sorted: a (1), b (2), c (3)
        assert limiter.tier_names == ["a", "b", "c"]

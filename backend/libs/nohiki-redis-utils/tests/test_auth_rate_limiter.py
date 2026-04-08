"""Tests for auth rate limiter functionality.

Provides coverage for authentication rate limiting
including login, registration, password reset, and failed login tracking.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_redis_utils.auth_rate_limiter import (
    AuthRateLimitConfig,
    AuthRateLimiter,
)
from nohiki_redis_utils.multi_tier_rate_limiter import (
    MultiTierCheckResult,
    MultiTierRateLimiter,
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


class TestAuthRateLimitConfig:
    """Tests for AuthRateLimitConfig dataclass."""

    def test_default_configuration(self) -> None:
        """Verify default configuration values are sensible."""
        config = AuthRateLimitConfig()

        assert config.login_per_minute == 5
        assert config.login_per_hour == 20
        assert config.register_per_hour == 3
        assert config.register_per_day == 10
        assert config.reset_per_hour == 3
        assert config.max_failed_logins == 10
        assert config.failed_login_window_seconds == 3600

    def test_custom_configuration(self) -> None:
        """Verify custom configuration overrides defaults."""
        config = AuthRateLimitConfig(
            login_per_minute=10,
            login_per_hour=50,
            register_per_hour=5,
            register_per_day=20,
            reset_per_hour=5,
            max_failed_logins=5,
            failed_login_window_seconds=1800,
        )

        assert config.login_per_minute == 10
        assert config.login_per_hour == 50
        assert config.register_per_hour == 5
        assert config.register_per_day == 20
        assert config.reset_per_hour == 5
        assert config.max_failed_logins == 5
        assert config.failed_login_window_seconds == 1800

    def test_partial_custom_configuration(self) -> None:
        """Verify partial custom configuration keeps defaults for others."""
        config = AuthRateLimitConfig(login_per_minute=3)

        assert config.login_per_minute == 3
        assert config.login_per_hour == 20  # Default
        assert config.register_per_hour == 3  # Default


class TestAuthRateLimiterInitialization:
    """Tests for AuthRateLimiter initialization and factory method."""

    def test_create_with_default_config(self) -> None:
        """Create limiter with default configuration."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        assert limiter is not None
        assert isinstance(limiter, AuthRateLimiter)

    def test_create_with_custom_config(self) -> None:
        """Create limiter with custom configuration."""
        mock_cache = MagicMock()
        config = AuthRateLimitConfig(login_per_minute=3, register_per_hour=1)

        limiter = AuthRateLimiter.create(mock_cache, config)

        assert limiter is not None
        assert limiter._config == config

    def test_create_builds_login_limiter(self) -> None:
        """Verify login limiter is built with correct tiers."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        assert isinstance(limiter._login_limiter, MultiTierRateLimiter)
        tier_names = limiter._login_limiter.tier_names
        assert "minute" in tier_names
        assert "hour" in tier_names

    def test_create_builds_register_limiter(self) -> None:
        """Verify register limiter is built with correct tiers."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        assert isinstance(limiter._register_limiter, MultiTierRateLimiter)
        tier_names = limiter._register_limiter.tier_names
        assert "hour" in tier_names
        assert "day" in tier_names

    def test_create_builds_reset_limiter(self) -> None:
        """Verify reset limiter is built."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        assert limiter._reset_limiter is not None

    def test_create_builds_failed_login_limiter(self) -> None:
        """Verify failed login limiter is built."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        assert limiter._failed_login_limiter is not None


class TestAuthRateLimiterCheckLogin:
    """Tests for check_login method."""

    @pytest.mark.asyncio
    async def test_check_login_allowed(self) -> None:
        """Login check returns allowed result when under limit."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        # Mock the underlying limiter to return allowed
        mock_result = MultiTierCheckResult(allowed=True, tier_results={})
        with patch.object(limiter._login_limiter, "check", AsyncMock(return_value=mock_result)):
            result = await limiter.check_login("user@example.com")

            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_login_denied(self) -> None:
        """Login check returns denied result when limit exceeded."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        # Mock the underlying limiter to return denied
        mock_result = MultiTierCheckResult(
            allowed=False,
            exceeded_tier="minute",
            retry_after=60.0,
            tier_results={},
        )
        with patch.object(limiter._login_limiter, "check", AsyncMock(return_value=mock_result)):
            result = await limiter.check_login("user@example.com")

            assert result.allowed is False
            assert result.exceeded_tier == "minute"
            assert result.retry_after == pytest.approx(60.0)


class TestAuthRateLimiterCheckRegister:
    """Tests for check_register method."""

    @pytest.mark.asyncio
    async def test_check_register_allowed(self) -> None:
        """Registration check returns allowed result when under limit."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        mock_result = MultiTierCheckResult(allowed=True, tier_results={})
        with patch.object(limiter._register_limiter, "check", AsyncMock(return_value=mock_result)):
            result = await limiter.check_register("192.168.1.1")

            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_register_denied(self) -> None:
        """Registration check returns denied result when limit exceeded."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        mock_result = MultiTierCheckResult(
            allowed=False,
            exceeded_tier="hour",
            retry_after=3600.0,
            tier_results={},
        )
        with patch.object(limiter._register_limiter, "check", AsyncMock(return_value=mock_result)):
            result = await limiter.check_register("192.168.1.1")

            assert result.allowed is False
            assert result.exceeded_tier == "hour"


class TestAuthRateLimiterCheckPasswordReset:
    """Tests for check_password_reset method."""

    @pytest.mark.asyncio
    async def test_check_password_reset_allowed(self) -> None:
        """Password reset check returns True when under limit."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        mock_result = create_rate_limit_result(allowed=True, remaining=2)
        with patch.object(limiter._reset_limiter, "check", AsyncMock(return_value=mock_result)):
            result = await limiter.check_password_reset("user@example.com")

            assert result is True

    @pytest.mark.asyncio
    async def test_check_password_reset_denied(self) -> None:
        """Password reset check returns False when limit exceeded."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        mock_result = create_rate_limit_result(allowed=False, remaining=0, retry_after=1800.0)
        with patch.object(limiter._reset_limiter, "check", AsyncMock(return_value=mock_result)):
            result = await limiter.check_password_reset("user@example.com")

            assert result is False


class TestAuthRateLimiterFailedLogins:
    """Tests for failed login tracking."""

    @pytest.mark.asyncio
    async def test_record_failed_login(self) -> None:
        """Record failed login returns failure count."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        # First failure
        mock_result = create_rate_limit_result(allowed=True, remaining=9)
        with patch.object(limiter._failed_login_limiter, "check", AsyncMock(return_value=mock_result)):
            count = await limiter.record_failed_login("user@example.com")

            assert count == 1

    @pytest.mark.asyncio
    async def test_record_multiple_failed_logins(self) -> None:
        """Record multiple failed logins increments count."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        # Simulate 3 failures
        mock_result = create_rate_limit_result(allowed=True, remaining=7)
        with patch.object(limiter._failed_login_limiter, "check", AsyncMock(return_value=mock_result)):
            count = await limiter.record_failed_login("user@example.com")

            assert count == 3

    @pytest.mark.asyncio
    async def test_clear_failed_logins(self) -> None:
        """Clear failed logins resets counter."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        with patch.object(limiter._failed_login_limiter, "reset", AsyncMock()) as mock_reset:
            await limiter.clear_failed_logins("user@example.com")

            mock_reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_failed_login_at_max(self) -> None:
        """Record failed login at max returns max failures."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        # Max failures reached
        mock_result = create_rate_limit_result(allowed=False, remaining=0, retry_after=3600.0)
        with patch.object(limiter._failed_login_limiter, "check", AsyncMock(return_value=mock_result)):
            count = await limiter.record_failed_login("user@example.com")

            assert count == 10  # max_failed_logins


class TestAuthRateLimiterReset:
    """Tests for reset methods."""

    @pytest.mark.asyncio
    async def test_reset_login(self) -> None:
        """Reset login rate limits for identifier."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        with patch.object(limiter._login_limiter, "reset_all", AsyncMock()) as mock_reset:
            await limiter.reset_login("user@example.com")

            mock_reset.assert_called_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_reset_register(self) -> None:
        """Reset registration rate limits for IP."""
        mock_cache = MagicMock()
        limiter = AuthRateLimiter.create(mock_cache)

        with patch.object(limiter._register_limiter, "reset_all", AsyncMock()) as mock_reset:
            await limiter.reset_register("192.168.1.1")

            mock_reset.assert_called_once_with("192.168.1.1")


class TestAuthRateLimiterConstructor:
    """Tests for direct constructor usage."""

    def test_constructor_assigns_limiters(self) -> None:
        """Constructor assigns all limiter components."""
        mock_login = MagicMock(spec=MultiTierRateLimiter)
        mock_register = MagicMock(spec=MultiTierRateLimiter)
        mock_reset = MagicMock()
        mock_failed = MagicMock()
        config = AuthRateLimitConfig()

        limiter = AuthRateLimiter(
            login_limiter=mock_login,
            register_limiter=mock_register,
            reset_limiter=mock_reset,
            failed_login_limiter=mock_failed,
            config=config,
        )

        assert limiter._login_limiter is mock_login
        assert limiter._register_limiter is mock_register
        assert limiter._reset_limiter is mock_reset
        assert limiter._failed_login_limiter is mock_failed
        assert limiter._config is config


class TestAuthRateLimiterIntegration:
    """Integration-style tests with mocked Redis cache."""

    @pytest.mark.asyncio
    async def test_full_auth_flow_allowed(self) -> None:
        """Full authentication flow with allowed results."""
        limiter = AuthRateLimiter.create(MagicMock())

        # Mock all underlying limiters to allow
        with (
            patch.object(
                limiter._login_limiter,
                "check",
                return_value=MultiTierCheckResult(allowed=True, tier_results={}),
            ),
            patch.object(
                limiter._register_limiter,
                "check",
                return_value=MultiTierCheckResult(allowed=True, tier_results={}),
            ),
            patch.object(
                limiter._reset_limiter,
                "check",
                return_value=create_rate_limit_result(allowed=True, remaining=3),
            ),
        ):
            login_result = await limiter.check_login("user@example.com")
            register_result = await limiter.check_register("192.168.1.1")
            reset_allowed = await limiter.check_password_reset("user@example.com")

            assert login_result.allowed is True
            assert register_result.allowed is True
            assert reset_allowed is True

    @pytest.mark.asyncio
    async def test_full_auth_flow_blocked(self) -> None:
        """Full authentication flow with blocked results."""
        limiter = AuthRateLimiter.create(MagicMock())

        # Mock all underlying limiters to block
        with (
            patch.object(
                limiter._login_limiter,
                "check",
                return_value=MultiTierCheckResult(
                    allowed=False,
                    exceeded_tier="minute",
                    retry_after=60.0,
                    tier_results={},
                ),
            ),
            patch.object(
                limiter._register_limiter,
                "check",
                return_value=MultiTierCheckResult(
                    allowed=False,
                    exceeded_tier="hour",
                    retry_after=3600.0,
                    tier_results={},
                ),
            ),
            patch.object(
                limiter._reset_limiter,
                "check",
                return_value=create_rate_limit_result(allowed=False, remaining=0, retry_after=1800.0),
            ),
        ):
            login_result = await limiter.check_login("user@example.com")
            register_result = await limiter.check_register("192.168.1.1")
            reset_allowed = await limiter.check_password_reset("user@example.com")

            assert login_result.allowed is False
            assert register_result.allowed is False
            assert reset_allowed is False


class TestAuthRateLimiterConfigValidation:
    """Tests for configuration edge cases."""

    def test_zero_limits_in_config(self) -> None:
        """Config with zero limits is accepted."""
        config = AuthRateLimitConfig(
            login_per_minute=0,
            login_per_hour=0,
        )

        assert config.login_per_minute == 0
        assert config.login_per_hour == 0

    def test_large_limits_in_config(self) -> None:
        """Config with large limits is accepted."""
        config = AuthRateLimitConfig(
            login_per_minute=10000,
            login_per_hour=100000,
        )

        assert config.login_per_minute == 10000
        assert config.login_per_hour == 100000

    def test_config_is_frozen_dataclass(self) -> None:
        """Config dataclass is frozen (immutable)."""
        assert dataclasses.is_dataclass(AuthRateLimitConfig)
        params = getattr(AuthRateLimitConfig, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

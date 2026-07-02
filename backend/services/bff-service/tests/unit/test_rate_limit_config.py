"""Tests for BFF rate limiting configuration classes."""

from __future__ import annotations

from bff_service.core.config import BFFCachingSettings, BFFRateLimitConfig


class TestBFFRateLimitConfig:
    """Tests for BFFRateLimitConfig."""

    def test_defaults_for_dev_environment(self) -> None:
        """Test that config has dev defaults when running in development."""
        config = BFFRateLimitConfig()

        assert config.enabled is True
        assert config.auth_requests_per_minute == 10000
        assert config.auth_requests_per_hour == 100000
        assert config.anon_requests_per_minute == 10000
        assert config.anon_requests_per_hour == 100000
        assert config.sensitive_requests_per_minute == 1000
        assert config.key_prefix == "ratelimit"

    def test_custom_values(self) -> None:
        """Test BFFRateLimitConfig with custom values."""
        config = BFFRateLimitConfig(
            enabled=False,
            auth_requests_per_minute=60,
            auth_requests_per_hour=1000,
            anon_requests_per_minute=10,
            anon_requests_per_hour=100,
            sensitive_requests_per_minute=5,
        )

        assert config.enabled is False
        assert config.auth_requests_per_minute == 60
        assert config.auth_requests_per_hour == 1000
        assert config.anon_requests_per_minute == 10
        assert config.anon_requests_per_hour == 100
        assert config.sensitive_requests_per_minute == 5


class TestBFFCachingSettings:
    """Tests for BFFCachingSettings."""

    def test_defaults(self) -> None:
        """Test BFFCachingSettings has correct defaults."""
        settings = BFFCachingSettings()

        assert isinstance(settings.bff_rate_limit, BFFRateLimitConfig)
        assert settings.bff_rate_limit.enabled is True

    def test_rate_limit_nested_config(self) -> None:
        """Test that bff_rate_limit is properly nested in caching settings."""
        settings = BFFCachingSettings(
            bff_rate_limit=BFFRateLimitConfig(enabled=False),
        )

        assert settings.bff_rate_limit.enabled is False

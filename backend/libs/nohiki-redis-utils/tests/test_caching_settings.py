"""Tests for caching configuration."""

from __future__ import annotations

from nohiki_redis_utils import (
    CacheKeyConfig,
    CacheTTLConfig,
    CachingSettings,
    CircuitBreakerSettings,
    ExternalAPIConfig,
    RateLimitSettings,
)


class TestCacheKeyConfig:
    """Tests for CacheKeyConfig."""

    def test_build_single_part(self) -> None:
        """Build key with single part."""
        config = CacheKeyConfig(prefix="user")
        result = config.build("123")
        assert result == "user:123"

    def test_build_multiple_parts(self) -> None:
        """Build key with multiple parts."""
        config = CacheKeyConfig(prefix="profile")
        result = config.build("user-123", "settings", "v1")
        assert result == "profile:user-123:settings:v1"

    def test_build_custom_separator(self) -> None:
        """Build key with custom separator."""
        config = CacheKeyConfig(prefix="cache", separator="-")
        result = config.build("item", "456")
        assert result == "cache-item-456"


class TestCacheTTLConfig:
    """Tests for CacheTTLConfig."""

    def test_default_values(self) -> None:
        """Default TTL values are set correctly."""
        config = CacheTTLConfig()
        assert config.short == 300
        assert config.medium == 3600
        assert config.long == 86400
        assert config.projection == 86400
        assert config.rate_limit_window == 60
        assert config.circuit_breaker == 300
        assert config.token == 3600
        assert config.fallback_state == 86400

    def test_custom_values(self) -> None:
        """Custom TTL values can be set."""
        config = CacheTTLConfig(short=60, projection=7200)
        assert config.short == 60
        assert config.projection == 7200


class TestRateLimitSettings:
    """Tests for RateLimitSettings."""

    def test_default_values(self) -> None:
        """Default rate limit values are set correctly."""
        config = RateLimitSettings()
        assert config.enabled is True
        assert config.requests_per_window == 100
        assert config.window_seconds == 60
        assert config.key_prefix == "ratelimit"

    def test_build_key(self) -> None:
        """Build rate limit key for identifier."""
        config = RateLimitSettings(key_prefix="limit")
        result = config.build_key("user-abc123")
        assert result == "limit:user-abc123"


class TestCircuitBreakerSettings:
    """Tests for CircuitBreakerSettings."""

    def test_default_values(self) -> None:
        """Default circuit breaker values are set correctly."""
        config = CircuitBreakerSettings()
        assert config.enabled is True
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 30
        assert config.half_open_max_calls == 3
        assert config.key_prefix == "circuit"

    def test_build_state_key(self) -> None:
        """Build circuit breaker state key."""
        config = CircuitBreakerSettings(key_prefix="cb")
        result = config.build_state_key("external-api")
        assert result == "cb:external-api:state"

    def test_build_failure_count_key(self) -> None:
        """Build circuit breaker failure count key."""
        config = CircuitBreakerSettings(key_prefix="breaker")
        result = config.build_failure_count_key("payment-service")
        assert result == "breaker:payment-service:failures"


class TestExternalAPIConfig:
    """Tests for ExternalAPIConfig."""

    def test_required_name(self) -> None:
        """Name is required."""
        config = ExternalAPIConfig(name="jsearch")
        assert config.name == "jsearch"

    def test_default_rate_limits(self) -> None:
        """Default rate limit values are set."""
        config = ExternalAPIConfig(name="openai")
        assert config.requests_per_minute == 60
        assert config.requests_per_hour == 1000
        assert config.requests_per_day == 10000
        assert config.fallback_ttl_seconds == 86400

    def test_rate_limit_key(self) -> None:
        """Build rate limit key for tier."""
        config = ExternalAPIConfig(name="jsearch")
        assert config.rate_limit_key("minute") == "api:jsearch:ratelimit:minute"
        assert config.rate_limit_key("hour") == "api:jsearch:ratelimit:hour"
        assert config.rate_limit_key("day") == "api:jsearch:ratelimit:day"

    def test_fallback_key(self) -> None:
        """Build fallback state key."""
        config = ExternalAPIConfig(name="openrouter")
        result = config.fallback_key()
        assert result == "api:openrouter:fallback"

    def test_health_key(self) -> None:
        """Build provider health state key."""
        config = ExternalAPIConfig(name="sendgrid")
        result = config.health_key()
        assert result == "api:sendgrid:health"


class TestCachingSettings:
    """Tests for CachingSettings."""

    def test_default_nested_configs(self) -> None:
        """Default nested configs are created."""
        settings = CachingSettings()
        assert isinstance(settings.ttls, CacheTTLConfig)
        assert isinstance(settings.rate_limit, RateLimitSettings)
        assert isinstance(settings.circuit_breaker, CircuitBreakerSettings)

    def test_build_key_simple(self) -> None:
        """Build simple cache key."""
        settings = CachingSettings()
        result = settings.build_key("user", "123", "profile")
        assert result == "user:123:profile"

    def test_build_key_with_global_prefix(self) -> None:
        """Build cache key with global prefix."""
        settings = CachingSettings(global_prefix="myservice")
        result = settings.build_key("user", "456")
        assert result == "myservice:user:456"

    def test_build_key_custom_separator(self) -> None:
        """Build cache key with custom separator."""
        settings = CachingSettings(separator="-")
        result = settings.build_key("cache", "item", "789")
        assert result == "cache-item-789"

    def test_build_key_with_global_prefix_and_custom_separator(self) -> None:
        """Build cache key with both global prefix and custom separator."""
        settings = CachingSettings(global_prefix="svc", separator="/")
        result = settings.build_key("data", "key")
        assert result == "svc/data/key"

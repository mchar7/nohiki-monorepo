"""Tests for nohiki-redis-utils public API."""

from __future__ import annotations

import nohiki_redis_utils as redis_utils


def test_high_level_caching_api_exported() -> None:
    """Verify high-level caching items are exported."""
    assert "CacheFactory" in redis_utils.__all__
    assert "RedisCache" in redis_utils.__all__
    assert "create_cache" in redis_utils.__all__
    assert "cached" in redis_utils.__all__
    assert "cached_sync" in redis_utils.__all__


def test_circuit_breaker_api_exported() -> None:
    """Verify circuit breaker decorator is exported."""
    assert "circuit_breaker" in redis_utils.__all__
    assert "CircuitOpenError" in redis_utils.__all__


def test_auth_rate_limiter_api_exported() -> None:
    """Verify auth rate limiter is exported."""
    assert "AuthRateLimiter" in redis_utils.__all__
    assert "AuthRateLimitConfig" in redis_utils.__all__


def test_simple_rate_limiter_api_exported() -> None:
    """Verify simple rate limiter factories are exported."""
    assert "create_token_bucket_limiter" in redis_utils.__all__
    assert "create_sliding_window_limiter" in redis_utils.__all__
    assert "RateLimiter" in redis_utils.__all__
    assert "RateLimitResult" in redis_utils.__all__


def test_health_api_exported() -> None:
    """Verify health check utilities are exported."""
    assert "ensure_redis_ready" in redis_utils.__all__
    assert "check_cache_health" in redis_utils.__all__
    assert "CacheHealthResult" in redis_utils.__all__
    assert "HealthStatus" in redis_utils.__all__


def test_utility_api_exported() -> None:
    """Verify utility functions are exported."""
    assert "make_cache_key" in redis_utils.__all__
    assert "DistributedLockError" in redis_utils.__all__


def test_advanced_features_available_via_submodules() -> None:
    """Advanced features should be importable from submodules."""
    from nohiki_redis_utils.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
    from nohiki_redis_utils.delayed_queue import DelayedTaskQueue
    from nohiki_redis_utils.metrics import RedisMetrics
    from nohiki_redis_utils.multi_tier_rate_limiter import (
        MultiTierRateLimiter,
        RateLimitTier,
    )
    from nohiki_redis_utils.retry_tracker import RedisRetryTracker

    assert MultiTierRateLimiter is not None
    assert RateLimitTier is not None
    assert CircuitBreaker is not None
    assert CircuitBreakerConfig is not None
    assert DelayedTaskQueue is not None
    assert RedisMetrics is not None
    assert RedisRetryTracker is not None

"""Redis cache utilities for Nohiki services.

High-level API (recommended):
    - CacheFactory, create_cache, RedisCache - Core caching
    - cached, cached_sync - Caching decorators
    - circuit_breaker, CircuitOpenError - Circuit breaker pattern
    - AuthRateLimiter, AuthRateLimitConfig - Auth rate limiting
    - create_token_bucket_limiter, create_sliding_window_limiter - Simple rate limiters
    - ensure_redis_ready, check_cache_health - Health checks

For advanced/internal use, import directly from submodules:
    - nohiki_redis_utils.multi_tier_rate_limiter
    - nohiki_redis_utils.rate_limiter
    - nohiki_redis_utils.circuit_breaker
    - nohiki_redis_utils.retry_tracker
    - nohiki_redis_utils.delayed_queue
    - nohiki_redis_utils.metrics
"""

from .auth_rate_limiter import AuthRateLimitConfig, AuthRateLimiter
from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .circuit_breaker_decorator import CircuitOpenError, circuit_breaker
from .decorators import cached, cached_sync
from .distributed_lock import DistributedLockError
from .factory import CacheFactory, create_cache
from .health import (
    CacheHealthResult,
    HealthStatus,
    RedisHealthProbe,
    check_cache_health,
    ensure_redis_ready,
)
from .helpers import make_cache_key
from .idempotency import check_and_mark_processed_redis
from .metrics import RedisMetrics, get_redis_metrics
from .rate_limiter import (
    RateLimiter,
    RateLimitFailurePolicy,
    RateLimitResult,
    create_sliding_window_limiter,
    create_token_bucket_limiter,
)
from .redis_cache import RedisCache
from .retry_tracker import InMemoryRetryTracker, RedisRetryTracker
from .settings import (
    CacheKeyConfig,
    CacheTTLConfig,
    CachingSettings,
    CircuitBreakerSettings,
    ExternalAPIConfig,
    HasRedisSettings,
    RateLimitSettings,
    RedisMixin,
    RedisSettings,
)

__all__ = [
    "AuthRateLimitConfig",
    "AuthRateLimiter",
    "CacheFactory",
    "CacheHealthResult",
    "CacheKeyConfig",
    "CacheTTLConfig",
    "CachingSettings",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerSettings",
    "CircuitOpenError",
    "DistributedLockError",
    "ExternalAPIConfig",
    "HasRedisSettings",
    "HealthStatus",
    "InMemoryRetryTracker",
    "RateLimitFailurePolicy",
    "RateLimitResult",
    "RateLimitSettings",
    "RateLimiter",
    "RedisCache",
    "RedisHealthProbe",
    "RedisMetrics",
    "RedisMixin",
    "RedisRetryTracker",
    "RedisSettings",
    "cached",
    "cached_sync",
    "check_and_mark_processed_redis",
    "check_cache_health",
    "circuit_breaker",
    "create_cache",
    "create_sliding_window_limiter",
    "create_token_bucket_limiter",
    "ensure_redis_ready",
    "get_redis_metrics",
    "make_cache_key",
]

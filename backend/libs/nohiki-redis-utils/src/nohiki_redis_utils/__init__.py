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

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from .circuit_breaker_decorator import CircuitOpenError, circuit_breaker
from .decorators import cached, cached_sync
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

if TYPE_CHECKING:
    from .auth_rate_limiter import AuthRateLimitConfig as AuthRateLimitConfig
    from .auth_rate_limiter import AuthRateLimiter as AuthRateLimiter
    from .distributed_lock import DistributedLockError as DistributedLockError
    from .metrics import RedisMetrics as RedisMetrics
    from .metrics import get_redis_metrics as get_redis_metrics
    from .rate_limiter import RateLimiter as RateLimiter
    from .rate_limiter import RateLimitFailurePolicy as RateLimitFailurePolicy
    from .rate_limiter import RateLimitResult as RateLimitResult
    from .rate_limiter import create_sliding_window_limiter as create_sliding_window_limiter
    from .rate_limiter import create_token_bucket_limiter as create_token_bucket_limiter

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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AuthRateLimitConfig": ("nohiki_redis_utils.auth_rate_limiter", "AuthRateLimitConfig"),
    "AuthRateLimiter": ("nohiki_redis_utils.auth_rate_limiter", "AuthRateLimiter"),
    "DistributedLockError": ("nohiki_redis_utils.distributed_lock", "DistributedLockError"),
    "RedisMetrics": ("nohiki_redis_utils.metrics", "RedisMetrics"),
    "get_redis_metrics": ("nohiki_redis_utils.metrics", "get_redis_metrics"),
    "RateLimiter": ("nohiki_redis_utils.rate_limiter", "RateLimiter"),
    "RateLimitFailurePolicy": ("nohiki_redis_utils.rate_limiter", "RateLimitFailurePolicy"),
    "RateLimitResult": ("nohiki_redis_utils.rate_limiter", "RateLimitResult"),
    "create_sliding_window_limiter": (
        "nohiki_redis_utils.rate_limiter",
        "create_sliding_window_limiter",
    ),
    "create_token_bucket_limiter": (
        "nohiki_redis_utils.rate_limiter",
        "create_token_bucket_limiter",
    ),
}


def __getattr__(name: str) -> object:
    """Lazy-import optional Redis features (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

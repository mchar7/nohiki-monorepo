"""Middleware components for Kafka message handlers.

Provides a composable middleware pattern for wrapping handler execution:
- Middleware protocol for custom middleware
- Built-in rate limiting middleware (requires [ratelimit] extra)
- Database session middleware
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_kafka_client.middleware.db_session import execute_with_db_session
from nohiki_kafka_client.middleware.protocol import Middleware, NextHandler, execute_middleware_chain

if TYPE_CHECKING:
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitAlgorithm as RateLimitAlgorithm,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitConfig as RateLimitConfig,
    )
    from nohiki_kafka_client.middleware.rate_limit import (
        RateLimitMiddleware as RateLimitMiddleware,
    )

__all__ = [
    "Middleware",
    "NextHandler",
    "RateLimitAlgorithm",
    "RateLimitConfig",
    "RateLimitMiddleware",
    "execute_middleware_chain",
    "execute_with_db_session",
]


def __getattr__(name: str) -> object:
    """Lazy import rate limiting components (requires [ratelimit] extra)."""
    if name in {"RateLimitAlgorithm", "RateLimitConfig", "RateLimitMiddleware"}:
        try:
            from nohiki_kafka_client.middleware import rate_limit  # noqa: PLC0415
        except ImportError as e:
            msg = f"{name} requires the [ratelimit] extra. Install with: pip install nohiki-kafka-client[ratelimit]"
            raise ImportError(msg) from e
        return getattr(rate_limit, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

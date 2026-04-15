"""Rate limiting middleware for enrichment service.

Provides lazy-loading rate limiting middleware that initializes Redis
connection on first use. This allows middleware to be passed at decorator
time while deferring Redis connection to runtime.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from nohiki_kafka_client import RateLimitConfig, RateLimitMiddleware
from nohiki_observability import get_logger
from nohiki_redis_utils import create_cache

if TYPE_CHECKING:
    import betterproto2
    from nohiki_kafka_client import MessageContext

logger = get_logger(__name__)


class LazyRateLimitMiddleware:
    """Rate limiting middleware that lazily initializes Redis connection.

    Defers Redis connection until first use, allowing middleware instances
    to be created at module import time before the application starts.

    Example:
        rate_limiter = LazyRateLimitMiddleware(
            service_name="job-ingest-enrichment-service",
            redis_url="redis://localhost:6379/0",
            config=RateLimitConfig(
                key="llm:enrichment",
                requests_per_window=10,
                window_seconds=60,
            ),
        )

    """

    __slots__ = ("_config", "_middleware", "_redis_url", "_service_name")

    def __init__(
        self,
        service_name: str,
        redis_url: str,
        config: RateLimitConfig,
    ) -> None:
        """Initialize lazy rate limit middleware.

        Args:
            service_name: Service name for Redis key prefixing.
            redis_url: Redis connection URL.
            config: Rate limit configuration.

        """
        self._service_name = service_name
        self._redis_url = redis_url
        self._config = config
        self._middleware: RateLimitMiddleware | None = None

    def _ensure_middleware(self) -> RateLimitMiddleware:
        """Lazily initialize the rate limiting middleware."""
        if self._middleware is None:
            cache = create_cache(self._service_name, redis_url=self._redis_url)
            self._middleware = RateLimitMiddleware(cache, self._config)
            logger.info(
                "Rate limiting middleware initialized",
                key=self._config.key,
                requests_per_window=self._config.requests_per_window,
                window_seconds=self._config.window_seconds,
            )
        return self._middleware

    async def __call__(
        self,
        message: betterproto2.Message,
        context: MessageContext,
        call_next: Callable[[betterproto2.Message, MessageContext], Awaitable[None]],
    ) -> None:
        """Execute rate limit check before proceeding.

        Args:
            message: The deserialized protobuf message.
            context: Message context.
            call_next: Next handler in the middleware chain.

        """
        middleware = self._ensure_middleware()
        await middleware(message, context, call_next)

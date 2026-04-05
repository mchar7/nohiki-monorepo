"""Rate limiting middleware for Kafka message handlers.

Provides distributed rate limiting using Redis-backed algorithms from
nohiki-redis-utils. When rate limit is exceeded, raises RateLimitedError
which triggers the Kafka retry mechanism with backoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from nohiki_common_exceptions import RateLimitedError
from nohiki_observability import get_logger
from nohiki_redis_utils import RateLimiter, create_sliding_window_limiter, create_token_bucket_limiter

from nohiki_kafka_client.middleware.protocol import NextHandler

if TYPE_CHECKING:
    import betterproto2
    from nohiki_redis_utils import RedisCache

    from nohiki_kafka_client.handlers import MessageContext

logger = get_logger(__name__)


class RateLimitAlgorithm(StrEnum):
    """Available rate limiting algorithms."""

    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"  # noqa: S105  # Not a password


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Configuration for rate limiting middleware.

    Attributes:
        key: Unique identifier for this rate limit bucket (e.g., "llm:enrichment").
        requests_per_window: Maximum requests allowed per time window.
        window_seconds: Time window duration in seconds.
        algorithm: Rate limiting algorithm to use.

    """

    key: str
    requests_per_window: int
    window_seconds: int = 60
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW


class RateLimitMiddleware:
    """Middleware that enforces rate limits using Redis.

    When rate limit is exceeded, raises RateLimitedError which is classified
    as retryable by the Kafka client's error handler. The message goes to
    the retry topic with exponential backoff.

    Example:
        middleware = RateLimitMiddleware(
            cache=redis_cache,
            config=RateLimitConfig(
                key="llm:enrichment",
                requests_per_window=10,
                window_seconds=60,
            ),
        )

    """

    __slots__ = ("_cache", "_config", "_key", "_limiter")

    def __init__(self, cache: RedisCache, config: RateLimitConfig) -> None:
        """Initialize rate limit middleware.

        Args:
            cache: RedisCache instance for distributed rate limiting.
            config: Rate limit configuration.

        """
        self._cache = cache
        self._config = config
        self._key = config.key
        self._limiter: RateLimiter = self._create_limiter()

    def _create_limiter(self) -> RateLimiter:
        """Create the appropriate rate limiter based on config."""
        match self._config.algorithm:
            case RateLimitAlgorithm.SLIDING_WINDOW:
                return create_sliding_window_limiter(
                    cache=self._cache,
                    requests=self._config.requests_per_window,
                    window_seconds=self._config.window_seconds,
                )
            case RateLimitAlgorithm.TOKEN_BUCKET:
                return create_token_bucket_limiter(
                    cache=self._cache,
                    requests=self._config.requests_per_window,
                    window_seconds=self._config.window_seconds,
                )
            case _:
                return create_sliding_window_limiter(
                    cache=self._cache,
                    requests=self._config.requests_per_window,
                    window_seconds=self._config.window_seconds,
                )

    async def __call__(
        self,
        message: betterproto2.Message,
        context: MessageContext,
        call_next: NextHandler,
    ) -> None:
        """Check rate limit before proceeding with handler execution.

        Args:
            message: The deserialized protobuf message.
            context: Message context.
            call_next: Next handler in the middleware chain.

        Raises:
            RateLimitedError: If rate limit is exceeded. This triggers
                the Kafka retry mechanism with backoff.

        """
        result = await self._limiter.check(self._key)

        if not result.allowed:
            logger.warning(
                "Rate limit exceeded",
                key=self._key,
                retry_after=result.retry_after,
                topic=context.topic,
                partition=context.partition,
                offset=context.offset,
            )
            raise RateLimitedError(
                service_name=self._key,
                retry_after_seconds=result.retry_after,
            )

        logger.debug(
            "Rate limit check passed",
            key=self._key,
            remaining=result.remaining,
        )

        await call_next(message, context)

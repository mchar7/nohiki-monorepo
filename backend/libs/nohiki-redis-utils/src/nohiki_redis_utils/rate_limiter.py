"""Distributed rate limiting via Redis."""
# ruff: noqa: S105  # False positive: _TOKEN_BUCKET_SCRIPT is a Lua script, not a password

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from redis.asyncio import RedisError

if TYPE_CHECKING:
    from .redis_cache import RedisCache

logger = get_logger(__name__)

# Expected number of elements in Lua script result
_SCRIPT_RESULT_LENGTH = 3


class RateLimitAlgorithm(Enum):
    """Available rate limiting algorithms."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"


class RateLimitFailurePolicy(Enum):
    """Behavior when the rate-limit backend cannot produce a valid decision."""

    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


@dataclass(slots=True)
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_at: float  # Unix timestamp
    retry_after: float | None = None  # Seconds until next allowed request


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Rate limit configuration."""

    requests: int  # Max requests allowed
    window_seconds: int  # Time window in seconds
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    burst_size: int | None = None  # For token bucket only, defaults to requests
    failure_policy: RateLimitFailurePolicy = RateLimitFailurePolicy.FAIL_OPEN


class RateLimiter(ABC):
    """Base rate limiter interface."""

    @abstractmethod
    async def check(self, key: str) -> RateLimitResult:
        """Check if request is allowed and consume one token if so."""

    @abstractmethod
    async def reset(self, key: str) -> None:
        """Reset rate limit for key."""


def _backend_failure_result(
    config: RateLimitConfig,
    *,
    now: float,
    open_remaining: int,
) -> RateLimitResult:
    """Map an unavailable limiter backend to its configured availability policy."""
    allowed = config.failure_policy == RateLimitFailurePolicy.FAIL_OPEN
    return RateLimitResult(
        allowed=allowed,
        remaining=open_remaining if allowed else 0,
        reset_at=now + config.window_seconds,
        retry_after=None if allowed else float(config.window_seconds),
    )


# Lua script for sliding window rate limiting using sorted sets
_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_start = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])

-- Remove expired entries
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Count current entries
local count = redis.call('ZCARD', key)

if count < limit then
    -- Add new entry with current timestamp as score and unique member
    redis.call('ZADD', key, now, now .. ':' .. math.random(1000000))
    redis.call('EXPIRE', key, window_seconds)
    return {1, limit - count - 1, 0}  -- allowed=1, remaining, retry_after=0
else
    -- Get oldest entry to calculate retry_after
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 0
    if oldest and #oldest >= 2 then
        retry_after = tonumber(oldest[2]) + window_seconds - now
        if retry_after < 0 then retry_after = 0 end
    end
    return {0, 0, retry_after}  -- allowed=0, remaining=0, retry_after
end
"""

# Lua script for token bucket rate limiting using hash
_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local bucket_size = tonumber(ARGV[2])
local refill_rate = tonumber(ARGV[3])
local window_seconds = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_update')
local tokens = tonumber(data[1]) or bucket_size
local last_update = tonumber(data[2]) or now

-- Refill tokens based on elapsed time
local elapsed = now - last_update
tokens = math.min(bucket_size, tokens + (elapsed * refill_rate))

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_update', now)
    redis.call('EXPIRE', key, window_seconds * 2)
    return {1, math.floor(tokens), 0}  -- allowed=1, remaining, retry_after=0
else
    -- Calculate time until next token
    local time_to_token = (1 - tokens) / refill_rate
    return {0, 0, time_to_token}  -- allowed=0, remaining=0, retry_after
end
"""


class SlidingWindowRateLimiter(RateLimiter):
    """Sliding window rate limiter using Redis sorted sets.

    This algorithm provides precise rate limiting by tracking each request
    timestamp in a sorted set. Memory usage is O(requests_per_window) per key.
    """

    def __init__(self, cache: RedisCache, config: RateLimitConfig) -> None:
        """Initialize sliding window rate limiter.

        Args:
            cache: Cache instance supporting eval_script
            config: Rate limit configuration

        """
        self._cache = cache
        self._config = config

    async def check(self, key: str) -> RateLimitResult:
        """Check if request is allowed and consume one slot if so.

        Args:
            key: Unique identifier for the rate limit bucket

        Returns:
            RateLimitResult with allowed status and metadata

        """
        now = time.time()
        window_start = now - self._config.window_seconds
        prefixed_key = f"ratelimit:sw:{key}"

        try:
            result = await self._cache.eval_script(
                _SLIDING_WINDOW_SCRIPT,
                keys=[prefixed_key],
                args=[
                    str(now),
                    str(window_start),
                    str(self._config.requests),
                    str(self._config.window_seconds),
                ],
            )

            if not result or len(result) < _SCRIPT_RESULT_LENGTH:
                logger.warning(
                    "Unexpected rate limit result",
                    key=key,
                    result=result,
                    failure_policy=self._config.failure_policy.value,
                )
                return _backend_failure_result(
                    self._config,
                    now=now,
                    open_remaining=self._config.requests - 1,
                )

            allowed = int(result[0]) == 1
            remaining = int(result[1])
            retry_after = float(result[2]) if not allowed else None

            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=now + self._config.window_seconds,
                retry_after=retry_after,
            )

        except Exception:  # noqa: BLE001 - backend failures are mapped by explicit policy
            logger.warning(
                "Rate limit check failed",
                key=key,
                failure_policy=self._config.failure_policy.value,
                exc_info=True,
            )
            return _backend_failure_result(
                self._config,
                now=now,
                open_remaining=self._config.requests - 1,
            )

    async def reset(self, key: str) -> None:
        """Reset rate limit for key by deleting the sorted set.

        Args:
            key: Unique identifier for the rate limit bucket

        """
        prefixed_key = f"ratelimit:sw:{key}"
        try:
            await self._cache.delete(prefixed_key)
        except RedisError:
            logger.warning("Failed to reset rate limit", key=key, exc_info=True)


class TokenBucketRateLimiter(RateLimiter):
    """Token bucket rate limiter using Redis hash.

    This algorithm allows bursts up to bucket_size while maintaining
    an average rate. Memory usage is O(1) per key.
    """

    def __init__(self, cache: RedisCache, config: RateLimitConfig) -> None:
        """Initialize token bucket rate limiter.

        Args:
            cache: Cache instance supporting eval_script
            config: Rate limit configuration

        """
        self._cache = cache
        self._config = config
        # Bucket size defaults to requests if not specified
        self._bucket_size = config.burst_size or config.requests
        # Refill rate: tokens per second to achieve requests/window
        self._refill_rate = config.requests / config.window_seconds

    async def check(self, key: str) -> RateLimitResult:
        """Check if request is allowed and consume one token if so.

        Args:
            key: Unique identifier for the rate limit bucket

        Returns:
            RateLimitResult with allowed status and metadata

        """
        now = time.time()
        prefixed_key = f"ratelimit:tb:{key}"

        try:
            result = await self._cache.eval_script(
                _TOKEN_BUCKET_SCRIPT,
                keys=[prefixed_key],
                args=[
                    str(now),
                    str(self._bucket_size),
                    str(self._refill_rate),
                    str(self._config.window_seconds),
                ],
            )

            if not result or len(result) < _SCRIPT_RESULT_LENGTH:
                logger.warning(
                    "Unexpected rate limit result",
                    key=key,
                    result=result,
                    failure_policy=self._config.failure_policy.value,
                )
                return _backend_failure_result(
                    self._config,
                    now=now,
                    open_remaining=self._bucket_size - 1,
                )

            allowed = int(result[0]) == 1
            remaining = int(result[1])
            retry_after = float(result[2]) if not allowed else None

            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=now + (1 / self._refill_rate),  # Time until next token
                retry_after=retry_after,
            )

        except Exception:  # noqa: BLE001 - backend failures are mapped by explicit policy
            logger.warning(
                "Rate limit check failed",
                key=key,
                failure_policy=self._config.failure_policy.value,
                exc_info=True,
            )
            return _backend_failure_result(
                self._config,
                now=now,
                open_remaining=self._bucket_size - 1,
            )

    async def reset(self, key: str) -> None:
        """Reset rate limit for key by deleting the hash.

        Args:
            key: Unique identifier for the rate limit bucket

        """
        prefixed_key = f"ratelimit:tb:{key}"
        try:
            await self._cache.delete(prefixed_key)
        except RedisError:
            logger.warning("Failed to reset rate limit", key=key, exc_info=True)


def create_rate_limiter(cache: RedisCache, config: RateLimitConfig) -> RateLimiter:
    """Create appropriate rate limiter based on configuration.

    Args:
        cache: Cache instance supporting eval_script
        config: Rate limit configuration

    Returns:
        Rate limiter instance based on configured algorithm

    """
    if config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
        return TokenBucketRateLimiter(cache, config)
    return SlidingWindowRateLimiter(cache, config)


def create_token_bucket_limiter(
    cache: RedisCache,
    requests: int,
    window_seconds: int,
    burst_size: int | None = None,
) -> RateLimiter:
    """Create a token bucket rate limiter with simple parameters.

    Token bucket allows bursts up to burst_size while maintaining
    an average rate of requests/window_seconds.

    Args:
        cache: Redis cache instance
        requests: Maximum requests per window
        window_seconds: Time window in seconds
        burst_size: Maximum burst size (defaults to requests)

    Returns:
        Configured token bucket rate limiter

    """
    config = RateLimitConfig(
        requests=requests,
        window_seconds=window_seconds,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        burst_size=burst_size,
    )
    return TokenBucketRateLimiter(cache, config)


def create_sliding_window_limiter(
    cache: RedisCache,
    requests: int,
    window_seconds: int,
) -> RateLimiter:
    """Create a sliding window rate limiter with simple parameters.

    Sliding window provides precise rate limiting by tracking each
    request timestamp. More accurate than token bucket but uses
    more memory (O(requests) per key).

    Args:
        cache: Redis cache instance
        requests: Maximum requests per window
        window_seconds: Time window in seconds

    Returns:
        Configured sliding window rate limiter

    """
    config = RateLimitConfig(
        requests=requests,
        window_seconds=window_seconds,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
    )
    return SlidingWindowRateLimiter(cache, config)

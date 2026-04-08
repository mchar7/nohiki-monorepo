"""Tests for distributed rate limiting implementation."""

from __future__ import annotations

import time
from typing import cast
from unittest.mock import AsyncMock

import pytest
from nohiki_redis_utils import RateLimitResult, RedisCache
from nohiki_redis_utils.rate_limit_decorator import RateLimitExceededError, rate_limited
from nohiki_redis_utils.rate_limiter import (
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitFailurePolicy,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    create_rate_limiter,
)
from redis.asyncio import RedisError


class MockCache:
    """Mock cache for testing rate limiters."""

    def __init__(self) -> None:
        """Initialize mock cache with async mocks."""
        self.eval_script_mock = AsyncMock()
        self.delete_mock = AsyncMock()

    async def eval_script(self, script: str, keys: list[str], args: list[str]) -> list[str]:
        """Execute mock Lua script."""
        result: list[str] = await self.eval_script_mock(script, keys, args)
        return result

    async def delete(self, key: str) -> None:
        """Delete mock key."""
        await self.delete_mock(key)

    def as_cache(self) -> RedisCache:
        """Cast mock to RedisCache for type checking."""
        return cast("RedisCache", self)


class TestSlidingWindowRateLimiter:
    """Tests for sliding window rate limiter."""

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self) -> None:
        """Requests under limit should be allowed."""
        cache = MockCache()
        # Return: allowed=1, remaining=4, retry_after=0
        cache.eval_script_mock.return_value = ["1", "4", "0"]

        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is True
        assert result.remaining == 4
        assert result.retry_after is None

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self) -> None:
        """Requests over limit should be blocked."""
        cache = MockCache()
        # Return: allowed=0, remaining=0, retry_after=30
        cache.eval_script_mock.return_value = ["0", "0", "30"]

        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_returns_correct_retry_after(self) -> None:
        """Retry after should reflect time until window slides."""
        cache = MockCache()
        # Return: allowed=0, remaining=0, retry_after=45.5
        cache.eval_script_mock.return_value = ["0", "0", "45.5"]

        config = RateLimitConfig(requests=10, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is False
        assert result.retry_after == pytest.approx(45.5)

    @pytest.mark.asyncio
    async def test_reset_deletes_key(self) -> None:
        """Reset should delete the rate limit key."""
        cache = MockCache()
        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        await limiter.reset("test_key")

        cache.delete_mock.assert_called_once_with("ratelimit:sw:test_key")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure",
        [RedisError("redis unavailable"), RuntimeError("circuit open"), [], ["malformed", "0", "0"]],
        ids=["redis-error", "circuit-open", "empty-result", "malformed-result"],
    )
    async def test_default_policy_fails_open_on_backend_failure(self, failure: object) -> None:
        cache = MockCache()
        if isinstance(failure, BaseException):
            cache.eval_script_mock.side_effect = failure
        else:
            cache.eval_script_mock.return_value = failure
        limiter = SlidingWindowRateLimiter(cache.as_cache(), RateLimitConfig(requests=5, window_seconds=60))

        result = await limiter.check("public-endpoint")

        assert result.allowed is True
        assert result.remaining == 4

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure",
        [RedisError("redis unavailable"), RuntimeError("circuit open"), [], ["malformed", "0", "0"]],
        ids=["redis-error", "circuit-open", "empty-result", "malformed-result"],
    )
    async def test_fail_closed_policy_denies_on_backend_failure(self, failure: object) -> None:
        cache = MockCache()
        if isinstance(failure, BaseException):
            cache.eval_script_mock.side_effect = failure
        else:
            cache.eval_script_mock.return_value = failure
        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
        )

        result = await SlidingWindowRateLimiter(cache.as_cache(), config).check("login")

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_uses_correct_key_prefix(self) -> None:
        """Should use ratelimit:sw: prefix for keys."""
        cache = MockCache()
        cache.eval_script_mock.return_value = ["1", "4", "0"]

        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        await limiter.check("my_key")

        call_args = cache.eval_script_mock.call_args
        assert call_args[0][1] == ["ratelimit:sw:my_key"]


class TestTokenBucketRateLimiter:
    """Tests for token bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_allows_burst_up_to_bucket_size(self) -> None:
        """Should allow burst requests up to bucket size."""
        cache = MockCache()
        # Return: allowed=1, remaining=9, retry_after=0
        cache.eval_script_mock.return_value = ["1", "9", "0"]

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            burst_size=10,
        )
        limiter = TokenBucketRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is True
        assert result.remaining == 9

    @pytest.mark.asyncio
    async def test_blocks_when_bucket_empty(self) -> None:
        """Should block when no tokens available."""
        cache = MockCache()
        # Return: allowed=0, remaining=0, retry_after=0.5
        cache.eval_script_mock.return_value = ["0", "0", "0.5"]

        config = RateLimitConfig(
            requests=10,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_uses_correct_key_prefix(self) -> None:
        """Should use ratelimit:tb: prefix for keys."""
        cache = MockCache()
        cache.eval_script_mock.return_value = ["1", "4", "0"]

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(cache.as_cache(), config)

        await limiter.check("my_key")

        call_args = cache.eval_script_mock.call_args
        assert call_args[0][1] == ["ratelimit:tb:my_key"]

    @pytest.mark.asyncio
    async def test_reset_deletes_key(self) -> None:
        """Reset should delete the rate limit key."""
        cache = MockCache()
        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(cache.as_cache(), config)

        await limiter.reset("test_key")

        cache.delete_mock.assert_called_once_with("ratelimit:tb:test_key")

    @pytest.mark.asyncio
    async def test_calculates_correct_refill_rate(self) -> None:
        """Refill rate should be requests/window_seconds."""
        cache = MockCache()
        cache.eval_script_mock.return_value = ["1", "4", "0"]

        config = RateLimitConfig(
            requests=60,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(cache.as_cache(), config)

        # 60 requests / 60 seconds = 1 token/second
        assert limiter._refill_rate == pytest.approx(1.0)

        await limiter.check("test_key")

        # Verify refill_rate is passed to script
        call_args = cache.eval_script_mock.call_args
        args = call_args[0][2]
        assert args[2] == "1.0"  # refill_rate


class TestCreateRateLimiter:
    """Tests for rate limiter factory function."""

    def test_creates_sliding_window_by_default(self) -> None:
        """Default algorithm should be sliding window."""
        cache = MockCache()
        config = RateLimitConfig(requests=10, window_seconds=60)

        limiter = create_rate_limiter(cache.as_cache(), config)

        assert isinstance(limiter, SlidingWindowRateLimiter)

    def test_creates_token_bucket_when_specified(self) -> None:
        """Should create token bucket when algorithm specified."""
        cache = MockCache()
        config = RateLimitConfig(
            requests=10,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )

        limiter = create_rate_limiter(cache.as_cache(), config)

        assert isinstance(limiter, TokenBucketRateLimiter)


class TestRateLimitedDecorator:
    """Tests for @rate_limited decorator."""

    @pytest.mark.asyncio
    async def test_allows_under_limit(self) -> None:
        """Decorated function should execute when under limit."""
        mock_cache = MockCache()
        mock_cache.eval_script_mock.return_value = ["1", "4", "0"]

        @rate_limited(requests=5, window_seconds=60, cache_factory=mock_cache.as_cache)
        async def my_func(user_id: str) -> str:
            return f"result_{user_id}"

        result = await my_func("user123")

        assert result == "result_user123"

    @pytest.mark.asyncio
    async def test_raises_when_limit_exceeded(self) -> None:
        """Should raise RateLimitExceededError when over limit."""
        mock_cache = MockCache()
        mock_cache.eval_script_mock.return_value = ["0", "0", "30"]

        @rate_limited(requests=5, window_seconds=60, cache_factory=mock_cache.as_cache)
        async def my_func(user_id: str) -> str:
            return f"result_{user_id}"

        with pytest.raises(RateLimitExceededError) as exc_info:
            await my_func("user123")

        assert exc_info.value.retry_after == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_returns_none_when_raise_on_limit_false(self) -> None:
        """Should return None when raise_on_limit=False and limit exceeded."""
        mock_cache = MockCache()
        mock_cache.eval_script_mock.return_value = ["0", "0", "30"]

        @rate_limited(
            requests=5,
            window_seconds=60,
            cache_factory=mock_cache.as_cache,
            raise_on_limit=False,
        )
        async def my_func(user_id: str) -> str:
            return f"result_{user_id}"

        result = await my_func("user123")

        assert result is None

    @pytest.mark.asyncio
    async def test_uses_custom_key_func(self) -> None:
        """Should use custom key function when provided."""
        mock_cache = MockCache()
        mock_cache.eval_script_mock.return_value = ["1", "4", "0"]

        @rate_limited(
            requests=5,
            window_seconds=60,
            key_func=lambda _args, kwargs: kwargs.get("user_id", "default"),
            cache_factory=mock_cache.as_cache,
        )
        async def my_func(user_id: str) -> str:
            return f"result_{user_id}"

        await my_func(user_id="custom_key")

        # Verify the key used includes the custom key
        call_args = mock_cache.eval_script_mock.call_args
        keys = call_args[0][1]
        assert "custom_key" in keys[0]

    @pytest.mark.asyncio
    async def test_uses_first_arg_as_default_key(self) -> None:
        """Default key should be first positional argument."""
        mock_cache = MockCache()
        mock_cache.eval_script_mock.return_value = ["1", "4", "0"]

        @rate_limited(requests=5, window_seconds=60, cache_factory=mock_cache.as_cache)
        async def my_func(user_id: str) -> str:
            return f"result_{user_id}"

        await my_func("user_abc")

        call_args = mock_cache.eval_script_mock.call_args
        keys = call_args[0][1]
        assert "user_abc" in keys[0]


class TestFailOpenBehavior:
    """Tests for fail-open behavior on Redis errors."""

    @pytest.mark.asyncio
    async def test_sliding_window_fails_open_on_error(self) -> None:
        """Sliding window should allow request on Redis error."""
        cache = MockCache()
        cache.eval_script_mock.side_effect = RedisError("Redis unavailable")

        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is True
        assert result.remaining == 4  # requests - 1

    @pytest.mark.asyncio
    async def test_token_bucket_fails_open_on_error(self) -> None:
        """Token bucket should allow request on Redis error."""
        cache = MockCache()
        cache.eval_script_mock.side_effect = RedisError("Redis unavailable")

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_fails_open_on_unexpected_result(self) -> None:
        """Should fail open when script returns unexpected result."""
        cache = MockCache()
        cache.eval_script_mock.return_value = []  # Empty result

        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(cache.as_cache(), config)

        result = await limiter.check("test_key")

        assert result.allowed is True


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_algorithm_is_sliding_window(self) -> None:
        """Default algorithm should be sliding window."""
        config = RateLimitConfig(requests=10, window_seconds=60)
        assert config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW

    def test_burst_size_defaults_to_none(self) -> None:
        """Burst size should default to None."""
        config = RateLimitConfig(requests=10, window_seconds=60)
        assert config.burst_size is None

    def test_can_set_burst_size(self) -> None:
        """Should be able to set custom burst size."""
        config = RateLimitConfig(
            requests=10,
            window_seconds=60,
            burst_size=20,
        )
        assert config.burst_size == 20


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_retry_after_defaults_to_none(self) -> None:
        """Retry after should default to None."""
        result = RateLimitResult(allowed=True, remaining=5, reset_at=time.time())
        assert result.retry_after is None

    def test_can_set_retry_after(self) -> None:
        """Should be able to set retry_after."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_at=time.time(),
            retry_after=30.0,
        )
        assert result.retry_after == pytest.approx(30.0)


class TestRateLimitExceededError:
    """Tests for RateLimitExceededError exception."""

    def test_stores_retry_after(self) -> None:
        """Exception should store retry_after value."""
        exc = RateLimitExceededError(retry_after=45.0)
        assert exc.retry_after == pytest.approx(45.0)

    def test_message_includes_retry_after(self) -> None:
        """Exception message should include retry_after."""
        exc = RateLimitExceededError(retry_after=45.0)
        assert "45.0" in str(exc)

    def test_message_without_retry_after(self) -> None:
        """Exception message should work without retry_after."""
        exc = RateLimitExceededError()
        assert "Rate limit exceeded" in str(exc)


class TestExtractKeyDefault:
    """Tests for _extract_key fallback to 'default'."""

    def test_returns_default_when_no_args_and_no_key_func(self) -> None:
        """_extract_key returns 'default' when no key_func and no positional args."""
        from nohiki_redis_utils.rate_limit_decorator import _extract_key

        result = _extract_key(None, (), {})
        assert result == "default"


class TestRateLimitedCachedLimiter:
    """Tests for rate_limited decorator reusing cached limiter."""

    @pytest.mark.asyncio
    async def test_ensure_initialized_returns_cached_limiter(self) -> None:
        """Second call to wrapped function reuses the cached limiter."""
        mock_cache = AsyncMock(spec=RedisCache)
        limiter = AsyncMock()
        limiter.check = AsyncMock(return_value=RateLimitResult(allowed=True, remaining=5, reset_at=0.0))

        from unittest.mock import patch

        with patch(
            "nohiki_redis_utils.rate_limit_decorator.create_rate_limiter",
            return_value=limiter,
        ) as mock_create:

            @rate_limited(
                requests=10,
                window_seconds=60,
                cache_factory=lambda: mock_cache,
            )
            async def my_func(key: str) -> str:
                return key

            await my_func("a")
            await my_func("b")

        assert mock_create.call_count == 1

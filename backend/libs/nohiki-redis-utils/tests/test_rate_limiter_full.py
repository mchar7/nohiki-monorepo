"""Tests for rate_limiter missing coverage lines.

This module covers missing lines in rate_limiter.py:
- Lines 218-219: RedisError in SlidingWindowRateLimiter.reset
- Lines 274-279: Unexpected result in TokenBucketRateLimiter
- Lines 320-321: RedisError in TokenBucketRateLimiter.reset
- Lines 363-369: create_token_bucket_limiter
- Lines 393-398: create_sliding_window_limiter
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_redis_utils.rate_limiter import (
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitFailurePolicy,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    create_sliding_window_limiter,
    create_token_bucket_limiter,
)
from redis.asyncio import RedisError


class TestSlidingWindowResetError:
    """Tests for SlidingWindowRateLimiter.reset error handling (lines 218-219)."""

    @pytest.mark.asyncio
    async def test_reset_handles_redis_error(self) -> None:
        """Should log warning on RedisError during reset (lines 218-219)."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(return_value=["1", "4", "0"])
        mock_cache.delete = AsyncMock(side_effect=RedisError("Connection failed"))

        config = RateLimitConfig(requests=5, window_seconds=60)
        limiter = SlidingWindowRateLimiter(mock_cache, config)

        # Should not raise
        await limiter.reset("test_key")


class TestTokenBucketUnexpectedResult:
    """Tests for TokenBucketRateLimiter unexpected result handling (lines 274-279)."""

    @pytest.mark.asyncio
    async def test_check_fails_open_on_empty_result(self) -> None:
        """Should fail open when eval_script returns empty (lines 274-279)."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(return_value=[])

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(mock_cache, config)

        result = await limiter.check("test_key")

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_fails_open_on_short_result(self) -> None:
        """Should fail open when eval_script returns short result."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(return_value=["1"])  # Only 1 element

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(mock_cache, config)

        result = await limiter.check("test_key")

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_fails_open_on_none_result(self) -> None:
        """Should fail open when eval_script returns None."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(return_value=None)

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(mock_cache, config)

        result = await limiter.check("test_key")

        assert result.allowed is True


class TestTokenBucketResetError:
    """Tests for TokenBucketRateLimiter.reset error handling (lines 320-321)."""

    @pytest.mark.asyncio
    async def test_reset_handles_redis_error(self) -> None:
        """Should log warning on RedisError during reset (lines 320-321)."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(return_value=["1", "4", "0"])
        mock_cache.delete = AsyncMock(side_effect=RedisError("Connection failed"))

        config = RateLimitConfig(
            requests=5,
            window_seconds=60,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        limiter = TokenBucketRateLimiter(mock_cache, config)

        # Should not raise
        await limiter.reset("test_key")


class TestFactoryFunctions:
    """Tests for factory functions (lines 363-369, 393-398)."""

    def test_create_token_bucket_limiter(self) -> None:
        """Should create TokenBucketRateLimiter (lines 363-369)."""
        mock_cache = MagicMock()

        limiter = create_token_bucket_limiter(
            cache=mock_cache,
            requests=10,
            window_seconds=60,
            burst_size=20,
        )

        assert isinstance(limiter, TokenBucketRateLimiter)

    def test_create_token_bucket_limiter_default_burst(self) -> None:
        """Should create TokenBucketRateLimiter with default burst_size."""
        mock_cache = MagicMock()

        limiter = create_token_bucket_limiter(
            cache=mock_cache,
            requests=10,
            window_seconds=60,
        )

        assert isinstance(limiter, TokenBucketRateLimiter)

    @pytest.mark.asyncio
    async def test_token_bucket_defaults_to_failing_open(self) -> None:
        """Existing callers pass no policy and must keep their availability bias."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(side_effect=RedisError("down"))

        limiter = create_token_bucket_limiter(cache=mock_cache, requests=10, window_seconds=60)

        assert (await limiter.check("k")).allowed is True

    @pytest.mark.asyncio
    async def test_token_bucket_can_fail_closed(self) -> None:
        """A caller whose bound must hold during an outage can select FAIL_CLOSED."""
        mock_cache = MagicMock()
        mock_cache.eval_script = AsyncMock(side_effect=RedisError("down"))

        limiter = create_token_bucket_limiter(
            cache=mock_cache,
            requests=10,
            window_seconds=60,
            failure_policy=RateLimitFailurePolicy.FAIL_CLOSED,
        )

        result = await limiter.check("k")

        assert result.allowed is False
        assert result.retry_after == 60.0

    def test_create_sliding_window_limiter(self) -> None:
        """Should create SlidingWindowRateLimiter (lines 393-398)."""
        mock_cache = MagicMock()

        limiter = create_sliding_window_limiter(
            cache=mock_cache,
            requests=10,
            window_seconds=60,
        )

        assert isinstance(limiter, SlidingWindowRateLimiter)

"""Unit tests for RateLimitMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_common_exceptions import RateLimitedError
from nohiki_kafka_client.middleware.rate_limit import (
    RateLimitAlgorithm,
    RateLimitConfig,
    RateLimitMiddleware,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self) -> None:
        """Config has sensible defaults."""
        config = RateLimitConfig(key="test:key", requests_per_window=10)

        assert config.key == "test:key"
        assert config.requests_per_window == 10
        assert config.window_seconds == 60
        assert config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW

    def test_custom_values(self) -> None:
        """Config accepts custom values."""
        config = RateLimitConfig(
            key="custom:key",
            requests_per_window=100,
            window_seconds=120,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )

        assert config.key == "custom:key"
        assert config.requests_per_window == 100
        assert config.window_seconds == 120
        assert config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET

    def test_frozen(self) -> None:
        """Config is immutable."""
        assert RateLimitConfig.__dataclass_params__.frozen


class TestRateLimitAlgorithm:
    """Tests for RateLimitAlgorithm enum."""

    def test_sliding_window_value(self) -> None:
        """SLIDING_WINDOW has correct string value."""
        assert RateLimitAlgorithm.SLIDING_WINDOW == "sliding_window"

    def test_token_bucket_value(self) -> None:
        """TOKEN_BUCKET has correct string value."""
        assert RateLimitAlgorithm.TOKEN_BUCKET == "token_bucket"


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def test_initialization_with_sliding_window(self) -> None:
        """Middleware initializes with sliding window algorithm."""
        mock_cache = MagicMock()
        mock_limiter = MagicMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "nohiki_kafka_client.middleware.rate_limit.create_sliding_window_limiter",
                MagicMock(return_value=mock_limiter),
            )

            config = RateLimitConfig(
                key="test:key",
                requests_per_window=10,
                window_seconds=60,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
            )
            middleware = RateLimitMiddleware(mock_cache, config)

            assert middleware._key == "test:key"
            assert middleware._limiter is mock_limiter

    def test_initialization_with_token_bucket(self) -> None:
        """Middleware initializes with token bucket algorithm."""
        mock_cache = MagicMock()
        mock_limiter = MagicMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "nohiki_kafka_client.middleware.rate_limit.create_token_bucket_limiter",
                MagicMock(return_value=mock_limiter),
            )

            config = RateLimitConfig(
                key="test:key",
                requests_per_window=10,
                window_seconds=60,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            )
            middleware = RateLimitMiddleware(mock_cache, config)

            assert middleware._limiter is mock_limiter

    @pytest.mark.asyncio
    async def test_call_allows_when_under_limit(self) -> None:
        """Middleware calls next handler when rate limit not exceeded."""
        mock_cache = MagicMock()
        mock_limiter = MagicMock()
        mock_limiter.check = AsyncMock(return_value=MagicMock(allowed=True, remaining=5))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "nohiki_kafka_client.middleware.rate_limit.create_sliding_window_limiter",
                MagicMock(return_value=mock_limiter),
            )

            config = RateLimitConfig(key="test:key", requests_per_window=10)
            middleware = RateLimitMiddleware(mock_cache, config)

            mock_message = MagicMock()
            mock_context = MagicMock(topic="test-topic", partition=0, offset=100)
            mock_call_next = AsyncMock()

            await middleware(mock_message, mock_context, mock_call_next)

            mock_limiter.check.assert_awaited_once_with("test:key")
            mock_call_next.assert_awaited_once_with(mock_message, mock_context)

    @pytest.mark.asyncio
    async def test_call_raises_when_limit_exceeded(self) -> None:
        """Middleware raises RateLimitedError when limit exceeded."""
        mock_cache = MagicMock()
        mock_limiter = MagicMock()
        mock_limiter.check = AsyncMock(return_value=MagicMock(allowed=False, retry_after=30))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "nohiki_kafka_client.middleware.rate_limit.create_sliding_window_limiter",
                MagicMock(return_value=mock_limiter),
            )

            config = RateLimitConfig(key="test:key", requests_per_window=10)
            middleware = RateLimitMiddleware(mock_cache, config)

            mock_message = MagicMock()
            mock_context = MagicMock(topic="test-topic", partition=0, offset=100)
            mock_call_next = AsyncMock()

            with pytest.raises(RateLimitedError) as exc_info:
                await middleware(mock_message, mock_context, mock_call_next)

            assert exc_info.value.retry_after_seconds == 30
            mock_call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_does_not_proceed_when_rate_limited(self) -> None:
        """When rate limited, the next handler is never called."""
        mock_cache = MagicMock()
        mock_limiter = MagicMock()
        mock_limiter.check = AsyncMock(return_value=MagicMock(allowed=False, retry_after=60))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "nohiki_kafka_client.middleware.rate_limit.create_sliding_window_limiter",
                MagicMock(return_value=mock_limiter),
            )

            config = RateLimitConfig(key="llm:enrichment", requests_per_window=5)
            middleware = RateLimitMiddleware(mock_cache, config)

            mock_call_next = AsyncMock()

            with pytest.raises(RateLimitedError):
                await middleware(MagicMock(), MagicMock(topic="t", partition=0, offset=0), mock_call_next)

            mock_call_next.assert_not_awaited()

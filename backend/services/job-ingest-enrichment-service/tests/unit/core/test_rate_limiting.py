"""Unit tests for LazyRateLimitMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_enrichment_service.core.rate_limiting import LazyRateLimitMiddleware
from nohiki_kafka_client import RateLimitConfig


class TestLazyRateLimitMiddleware:
    """Tests for LazyRateLimitMiddleware."""

    def test_initialization(self) -> None:
        """Middleware initializes without creating Redis connection."""
        config = RateLimitConfig(key="test:key", requests_per_window=10, window_seconds=60)

        middleware = LazyRateLimitMiddleware(
            service_name="test-service",
            redis_url="redis://localhost:6379/0",
            config=config,
        )

        assert middleware._service_name == "test-service"
        assert middleware._redis_url == "redis://localhost:6379/0"
        assert middleware._config is config
        assert middleware._middleware is None

    @pytest.mark.asyncio
    async def test_call_initializes_middleware_lazily(self) -> None:
        """First call initializes the underlying middleware."""
        config = RateLimitConfig(key="test:key", requests_per_window=10, window_seconds=60)
        middleware = LazyRateLimitMiddleware(
            service_name="test-service",
            redis_url="redis://localhost:6379/0",
            config=config,
        )

        mock_inner_middleware = AsyncMock()
        mock_cache = MagicMock()
        mock_message = MagicMock()
        mock_context = MagicMock()
        mock_call_next = AsyncMock()

        with (
            patch(
                "job_ingest_enrichment_service.core.rate_limiting.create_cache",
                return_value=mock_cache,
            ) as mock_create_cache,
            patch(
                "job_ingest_enrichment_service.core.rate_limiting.RateLimitMiddleware",
                return_value=mock_inner_middleware,
            ) as mock_middleware_cls,
        ):
            await middleware(mock_message, mock_context, mock_call_next)

            mock_create_cache.assert_called_once_with("test-service", redis_url="redis://localhost:6379/0")
            mock_middleware_cls.assert_called_once_with(mock_cache, config)
            mock_inner_middleware.assert_awaited_once_with(mock_message, mock_context, mock_call_next)

    @pytest.mark.asyncio
    async def test_call_reuses_middleware_on_subsequent_calls(self) -> None:
        """Subsequent calls reuse the already-initialized middleware."""
        config = RateLimitConfig(key="test:key", requests_per_window=10, window_seconds=60)
        middleware = LazyRateLimitMiddleware(
            service_name="test-service",
            redis_url="redis://localhost:6379/0",
            config=config,
        )

        mock_inner_middleware = AsyncMock()
        mock_cache = MagicMock()

        with (
            patch(
                "job_ingest_enrichment_service.core.rate_limiting.create_cache",
                return_value=mock_cache,
            ) as mock_create_cache,
            patch(
                "job_ingest_enrichment_service.core.rate_limiting.RateLimitMiddleware",
                return_value=mock_inner_middleware,
            ),
        ):
            await middleware(MagicMock(), MagicMock(), AsyncMock())
            await middleware(MagicMock(), MagicMock(), AsyncMock())
            await middleware(MagicMock(), MagicMock(), AsyncMock())

            mock_create_cache.assert_called_once()
            assert mock_inner_middleware.await_count == 3

    def test_ensure_middleware_creates_on_first_call(self) -> None:
        """_ensure_middleware creates middleware on first call."""
        config = RateLimitConfig(key="test:key", requests_per_window=10, window_seconds=60)
        middleware = LazyRateLimitMiddleware(
            service_name="test-service",
            redis_url="redis://localhost:6379/0",
            config=config,
        )

        mock_cache = MagicMock()
        mock_inner = MagicMock()

        with (
            patch(
                "job_ingest_enrichment_service.core.rate_limiting.create_cache",
                return_value=mock_cache,
            ),
            patch(
                "job_ingest_enrichment_service.core.rate_limiting.RateLimitMiddleware",
                return_value=mock_inner,
            ),
        ):
            result = middleware._ensure_middleware()

            assert result is mock_inner
            assert middleware._middleware is mock_inner

    def test_ensure_middleware_returns_cached_on_subsequent_calls(self) -> None:
        """_ensure_middleware returns cached middleware on subsequent calls."""
        config = RateLimitConfig(key="test:key", requests_per_window=10, window_seconds=60)
        middleware = LazyRateLimitMiddleware(
            service_name="test-service",
            redis_url="redis://localhost:6379/0",
            config=config,
        )

        mock_inner = MagicMock()
        middleware._middleware = mock_inner

        result = middleware._ensure_middleware()

        assert result is mock_inner

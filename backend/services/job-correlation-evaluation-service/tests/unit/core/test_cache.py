"""Unit tests for core/cache.py module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_correlation_evaluation_service.core.cache import (
    _CacheHolder,
    close_cache,
    get_cache,
    reset_cache,
)


class TestGetCache:
    """Tests for get_cache function."""

    def setup_method(self) -> None:
        """Reset cache holder before each test."""
        reset_cache()

    def teardown_method(self) -> None:
        """Reset cache holder after each test."""
        reset_cache()

    def test_creates_cache_on_first_call(self) -> None:
        """Test cache is created on first call."""
        with patch("job_correlation_evaluation_service.core.cache.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_create.return_value = mock_cache

            result = get_cache()

            mock_create.assert_called_once()
            assert result is mock_cache

    def test_returns_cached_instance(self) -> None:
        """Test subsequent calls return cached instance."""
        with patch("job_correlation_evaluation_service.core.cache.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_create.return_value = mock_cache

            result1 = get_cache()
            result2 = get_cache()

            mock_create.assert_called_once()
            assert result1 is result2

    def test_uses_provided_settings(self) -> None:
        """Test cache uses provided settings."""
        mock_settings = MagicMock()
        mock_settings.service_name = "test-service"
        mock_settings.redis.connection_string = "redis://test:6379"

        with patch("job_correlation_evaluation_service.core.cache.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_create.return_value = mock_cache

            get_cache(settings=mock_settings)

            mock_create.assert_called_once_with(
                "test-service",
                redis_url="redis://test:6379",
            )


class TestCloseCache:
    """Tests for close_cache function."""

    def teardown_method(self) -> None:
        """Reset cache holder after each test."""
        reset_cache()

    @pytest.mark.asyncio
    async def test_closes_cache_when_initialized(self) -> None:
        """Test cache is closed when initialized."""
        mock_cache = AsyncMock()
        _CacheHolder.instance = mock_cache

        await close_cache()

        mock_cache.close.assert_awaited_once()
        assert _CacheHolder.instance is None

    @pytest.mark.asyncio
    async def test_noop_when_not_initialized(self) -> None:
        """Test close is no-op when cache not initialized."""
        reset_cache()

        await close_cache()

        assert _CacheHolder.instance is None


class TestResetCache:
    """Tests for reset_cache function."""

    def test_clears_cache_holder(self) -> None:
        """Test reset clears the cache holder."""
        _CacheHolder.instance = MagicMock()

        reset_cache()

        assert _CacheHolder.instance is None

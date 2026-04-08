"""Tests for CacheManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCacheManager:
    """Tests for CacheManager class."""

    def test_init(self) -> None:
        """Test CacheManager initialization."""
        from nohiki_redis_utils.manager import CacheManager

        manager = CacheManager("test-service", redis_url="redis://localhost:6379")
        assert manager.service_name == "test-service"
        assert manager.redis_url == "redis://localhost:6379"
        assert manager._cache_instance is None

    def test_get_cache_creates_instance(self) -> None:
        """Test get_cache creates cache instance."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            cache = manager.get_cache()

            assert cache is mock_cache
            mock_create.assert_called_once_with("test-service", redis_url="redis://localhost:6379")

    def test_get_cache_returns_cached_instance(self) -> None:
        """Test get_cache returns cached instance on subsequent calls."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            cache1 = manager.get_cache()
            cache2 = manager.get_cache()

            assert cache1 is cache2
            assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_get(self) -> None:
        """Test get method."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_cache.get = AsyncMock(return_value="cached_value")
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            result = await manager.get("test_key")

            assert result == "cached_value"
            mock_cache.get.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_set(self) -> None:
        """Test set method."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_cache.set = AsyncMock()
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            await manager.set("test_key", "test_value", ttl=300)

            mock_cache.set.assert_called_once_with("test_key", "test_value", 300)

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        """Test delete method."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_cache.delete = AsyncMock()
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            await manager.delete("test_key")

            mock_cache.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_exists(self) -> None:
        """Test exists method."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_cache.exists = AsyncMock(return_value=True)
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            result = await manager.exists("test_key")

            assert result is True
            mock_cache.exists.assert_called_once_with("test_key")

    def test_reset_for_testing(self) -> None:
        """Test reset_for_testing method."""
        from nohiki_redis_utils.manager import CacheManager

        with patch("nohiki_redis_utils.manager.create_cache") as mock_create:
            mock_cache = MagicMock()
            mock_create.return_value = mock_cache

            manager = CacheManager("test-service", redis_url="redis://localhost:6379")
            manager.get_cache()
            assert manager._cache_instance is not None

            manager.reset_for_testing()
            assert manager._cache_instance is None

"""Tests for CacheFactory lifecycle management."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_redis_utils.factory import CacheCreationError, CacheFactory, create_cache


class TestCacheFactory:
    """Tests for CacheFactory class."""

    def setup_method(self) -> None:
        """Clear factory state before each test."""
        CacheFactory.clear_instances()

    def teardown_method(self) -> None:
        """Clear factory state after each test."""
        CacheFactory.clear_instances()

    def test_create_cache_returns_redis_cache(self) -> None:
        """Verify create_cache returns a RedisCache instance."""
        with patch("nohiki_redis_utils.factory.RedisCache") as mock_cache_class:
            mock_cache = MagicMock()
            mock_cache_class.return_value = mock_cache

            cache = CacheFactory.create_cache("test-service", redis_url="redis://localhost:6379")

            assert cache is mock_cache

    def test_create_cache_uses_redis_url_verbatim(self) -> None:
        """Verify create_cache passes the configured Redis DSN unchanged."""
        redis_url = "redis://localhost:6379/5"

        with patch("nohiki_redis_utils.factory.RedisCache") as mock_cache_class:
            CacheFactory.create_cache("svc", redis_url=redis_url)

        mock_cache_class.assert_called_once_with(redis_url, "svc")

    def test_create_cache_caches_instances(self) -> None:
        """Verify same instance is returned for same service."""
        with patch("nohiki_redis_utils.factory.RedisCache") as mock_cache_class:
            mock_cache = MagicMock()
            mock_cache_class.return_value = mock_cache

            cache1 = CacheFactory.create_cache("test-service", redis_url="redis://localhost:6379")
            cache2 = CacheFactory.create_cache("test-service", redis_url="redis://localhost:6379")

            assert cache1 is cache2
            mock_cache_class.assert_called_once()

    def test_create_cache_different_services_different_instances(self) -> None:
        """Verify different services get different instances."""
        with patch("nohiki_redis_utils.factory.RedisCache") as mock_cache_class:
            mock_cache1 = MagicMock()
            mock_cache2 = MagicMock()
            mock_cache_class.side_effect = [mock_cache1, mock_cache2]

            cache1 = CacheFactory.create_cache("service-a", redis_url="redis://localhost:6379")
            cache2 = CacheFactory.create_cache("service-b", redis_url="redis://localhost:6379")

            assert cache1 is not cache2

    def test_clear_instances(self) -> None:
        """Verify clear_instances clears the cache."""
        with patch("nohiki_redis_utils.factory.RedisCache") as mock_cache_class:
            mock_cache = MagicMock()
            mock_cache_class.return_value = mock_cache

            CacheFactory.create_cache("test-service", redis_url="redis://localhost:6379")

            assert len(CacheFactory._instances) == 1

            CacheFactory.clear_instances()

            assert len(CacheFactory._instances) == 0

    @pytest.mark.asyncio
    async def test_clear_instances_cancels_pending_closes(self) -> None:
        """Verify clear_instances cancels scheduled close tasks."""
        never_set = asyncio.Event()
        task = asyncio.create_task(never_set.wait())
        CacheFactory._pending_closes.add(task)

        CacheFactory.clear_instances()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        assert CacheFactory._pending_closes == set()

    @pytest.mark.asyncio
    async def test_close_all_closes_connections(self) -> None:
        """Verify close_all closes all cached Redis connections."""
        mock_cache1 = AsyncMock()
        mock_cache2 = AsyncMock()

        CacheFactory._instances["service-a"] = mock_cache1
        CacheFactory._instances["service-b"] = mock_cache2
        CacheFactory._instance_loop_ids["service-a"] = None
        CacheFactory._instance_loop_ids["service-b"] = None

        await CacheFactory.close_all()

        mock_cache1.close.assert_awaited_once()
        mock_cache2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_clears_instances(self) -> None:
        """Verify close_all clears instance cache."""
        mock_cache = AsyncMock()

        CacheFactory._instances["test-service"] = mock_cache
        CacheFactory._instance_loop_ids["test-service"] = None

        await CacheFactory.close_all()

        assert len(CacheFactory._instances) == 0
        assert len(CacheFactory._instance_loop_ids) == 0

    @pytest.mark.asyncio
    async def test_close_all_idempotent(self) -> None:
        """Verify multiple close_all calls are safe."""
        await CacheFactory.close_all()
        await CacheFactory.close_all()
        await CacheFactory.close_all()

    @pytest.mark.asyncio
    async def test_close_all_handles_closed_loop_error(self) -> None:
        """Verify close_all handles 'Event loop is closed' errors."""
        mock_cache = AsyncMock()
        mock_cache.close.side_effect = RuntimeError("Event loop is closed")

        CacheFactory._instances["test-service"] = mock_cache
        CacheFactory._instance_loop_ids["test-service"] = None

        await CacheFactory.close_all()

        assert len(CacheFactory._instances) == 0

    @pytest.mark.asyncio
    async def test_close_all_raises_other_runtime_errors(self) -> None:
        """Verify close_all raises non-loop RuntimeErrors."""
        mock_cache = AsyncMock()
        mock_cache.close.side_effect = RuntimeError("Some other error")

        CacheFactory._instances["test-service"] = mock_cache
        CacheFactory._instance_loop_ids["test-service"] = None

        with pytest.raises(RuntimeError, match="Some other error"):
            await CacheFactory.close_all()

    @pytest.mark.asyncio
    async def test_close_all_drains_pending_closes_on_current_loop(self) -> None:
        """Verify close_all waits for scheduled close tasks on its loop."""

        async def pending_close() -> None:
            await asyncio.sleep(0)

        task = asyncio.create_task(pending_close())
        CacheFactory._pending_closes.add(task)

        await CacheFactory.close_all()

        assert task.done()
        assert not task.cancelled()
        assert CacheFactory._pending_closes == set()


class TestCreateCacheFunction:
    """Tests for create_cache convenience function."""

    def setup_method(self) -> None:
        """Clear factory state before each test."""
        CacheFactory.clear_instances()

    def teardown_method(self) -> None:
        """Clear factory state after each test."""
        CacheFactory.clear_instances()

    def test_create_cache_delegates_to_factory(self) -> None:
        """Verify create_cache function delegates to CacheFactory."""
        with patch("nohiki_redis_utils.factory.RedisCache") as mock_cache_class:
            mock_cache = MagicMock()
            mock_cache_class.return_value = mock_cache

            cache = create_cache("test-service", redis_url="redis://localhost:6379")

            assert cache is mock_cache


class TestCacheCreationError:
    """Tests for CacheCreationError exception."""

    def test_exception_is_exception_subclass(self) -> None:
        """Verify CacheCreationError is an Exception."""
        error = CacheCreationError("test error")
        assert isinstance(error, Exception)

    def test_exception_message(self) -> None:
        """Verify exception message is preserved."""
        error = CacheCreationError("test error message")
        assert str(error) == "test error message"


class TestCacheFactoryEventLoopHandling:
    """Tests for CacheFactory event loop detection and cache invalidation."""

    def setup_method(self) -> None:
        """Clear factory state before each test."""
        CacheFactory.clear_instances()

    def teardown_method(self) -> None:
        """Clear factory state after each test."""
        CacheFactory.clear_instances()

    @pytest.mark.asyncio
    async def test_creates_fresh_cache_when_event_loop_changes(self) -> None:
        """Verify fresh cache is created when event loop ID differs from cached."""
        mock_cache_old = AsyncMock()
        mock_cache_new = MagicMock()

        CacheFactory._instances["test-service"] = mock_cache_old
        CacheFactory._instance_loop_ids["test-service"] = 99999

        with patch("nohiki_redis_utils.factory.RedisCache", return_value=mock_cache_new):
            cache = CacheFactory.create_cache("test-service", redis_url="redis://localhost:6379")

        assert cache is mock_cache_new
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        mock_cache_old.close.assert_awaited_once()
        assert CacheFactory._pending_closes == set()

    @pytest.mark.asyncio
    async def test_evicted_cache_is_closed_and_pending_task_self_discards(self) -> None:
        """Verify a stale loop cache is closed after eviction."""
        old_cache = AsyncMock()
        new_cache = MagicMock()
        CacheFactory._instances["svc"] = old_cache
        CacheFactory._instance_loop_ids["svc"] = 99999

        with patch("nohiki_redis_utils.factory.RedisCache", return_value=new_cache):
            cache = CacheFactory.create_cache("svc", redis_url="redis://localhost:6379")

        assert cache is new_cache
        assert len(CacheFactory._pending_closes) == 1
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        old_cache.close.assert_awaited_once()
        assert CacheFactory._pending_closes == set()

    @pytest.mark.asyncio
    async def test_get_current_loop_id_returns_id_when_loop_running(self) -> None:
        """Verify _get_current_loop_id returns loop ID inside async context."""
        loop_id = CacheFactory._get_current_loop_id()
        assert loop_id is not None
        assert isinstance(loop_id, int)

    def test_create_redis_cache_raises_on_creation_error(self) -> None:
        """Verify _create_redis_cache wraps CacheCreationError."""
        with (
            patch(
                "nohiki_redis_utils.factory.RedisCache",
                side_effect=CacheCreationError("Connection refused"),
            ),
            pytest.raises(CacheCreationError, match="Failed to create Redis cache"),
        ):
            CacheFactory._create_redis_cache("test-service", "redis://localhost:6379")

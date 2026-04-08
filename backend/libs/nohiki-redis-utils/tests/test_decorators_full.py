"""Tests for cache decorator error handling and edge cases."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from nohiki_redis_utils.decorators import (
    CacheOperationError,
    _get_cache_key,
    _should_bypass_cache,
    _try_cache_get,
    _try_cache_set,
    cached,
    cached_sync,
)
from nohiki_redis_utils.redis_cache import RedisCache


@pytest.fixture(autouse=True)
def _close_stale_event_loop() -> Generator[None]:
    """Close the stale event loop that pytest-asyncio auto-creates.

    asyncio.run() (used by cached_sync) sets the current event loop to None on
    completion.  pytest-asyncio's fixture teardown then calls
    asyncio.get_event_loop() which auto-creates a *new* unmanaged loop that
    nobody ever closes, triggering ResourceWarning on GC.

    Root cause confirmed via ``python -X tracemalloc``: the allocation is in
    ``pytest_asyncio/plugin.py:649 -> asyncio.get_event_loop()``.
    """
    yield
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.close()
    except RuntimeError:
        pass


class TestTryCacheGetErrors:
    """Tests for _try_cache_get error handling."""

    @pytest.mark.asyncio
    async def test_logs_warning_on_cache_operation_error(self) -> None:
        """Should log warning when CacheOperationError occurs."""
        mock_cache = MagicMock(spec=RedisCache)

        async def _get(*_a: object, **_kw: object) -> None:
            msg = "Redis down"
            raise CacheOperationError(msg)

        mock_cache.get = _get

        with patch("nohiki_redis_utils.decorators.logger") as mock_logger:
            result = await _try_cache_get(mock_cache, "key", "func")

        assert result is None
        mock_logger.warning.assert_called_once()
        assert "Cache get failed" in str(mock_logger.warning.call_args)


class TestTryCacheSetErrors:
    """Tests for _try_cache_set error handling."""

    @pytest.mark.asyncio
    async def test_logs_warning_on_cache_operation_error(self) -> None:
        """Should log warning when CacheOperationError occurs."""
        mock_cache = MagicMock(spec=RedisCache)

        async def _set(*_a: object, **_kw: object) -> None:
            msg = "Redis down"
            raise CacheOperationError(msg)

        mock_cache.set = _set

        with patch("nohiki_redis_utils.decorators.logger") as mock_logger:
            await _try_cache_set(mock_cache, "key", "value", 60, "func")

        mock_logger.warning.assert_called_once()
        assert "Cache set failed" in str(mock_logger.warning.call_args)


class TestGetCacheKey:
    """Tests for _get_cache_key with custom builder."""

    def test_uses_custom_key_builder(self) -> None:
        """Should use custom key_builder when provided."""

        def custom_builder(prefix: str, args: tuple, kwargs: dict) -> str:
            return f"{prefix}:{args[0]}:{kwargs.get('user', 'anon')}"

        result = _get_cache_key("test", ("arg1",), {"user": "john"}, custom_builder)

        assert result == "test:arg1:john"


class TestShouldBypassCache:
    """Tests for _should_bypass_cache."""

    def test_returns_true_when_skip_kwarg_present(self) -> None:
        """Should return True when bypass_cache is True."""
        kwargs = {"bypass_cache": True}
        result = _should_bypass_cache(kwargs, "bypass_cache")
        assert result is True
        assert "bypass_cache" not in kwargs  # Should be popped

    def test_returns_false_when_skip_kwarg_missing(self) -> None:
        """Should return False when bypass_cache is not present."""
        kwargs = {"other_arg": "value"}
        result = _should_bypass_cache(kwargs, "bypass_cache")
        assert result is False


class TestCachedInvalidateError:
    """Tests for cached decorator invalidate error handling."""

    @pytest.mark.asyncio
    async def test_invalidate_logs_warning_on_error(self) -> None:
        """Should log warning when cache delete fails."""
        mock_cache = MagicMock(spec=RedisCache)

        async def _get(*_a: object, **_kw: object) -> None:
            return None

        async def _set(*_a: object, **_kw: object) -> None:
            return

        async def _delete(*_a: object, **_kw: object) -> None:
            msg = "Delete failed"
            raise CacheOperationError(msg)

        mock_cache.get = _get
        mock_cache.set = _set
        mock_cache.delete = _delete

        @cached(key_prefix="test", cache_factory=lambda: mock_cache)
        async def test_func(x: int) -> int:
            return x * 2

        await test_func(5)

        with patch("nohiki_redis_utils.decorators.logger") as mock_logger:
            await test_func.invalidate(5)

            mock_logger.warning.assert_called_once()


def _make_sync_mock_cache(
    get_return: object = None,
    delete_side_effect: Exception | None = None,
) -> MagicMock:
    """Create a mock RedisCache using plain coroutines instead of AsyncMock.

    AsyncMock holds internal event loop references that cause ResourceWarning
    when GC runs after the temporary event loop from _run_async_with_cache closes.
    """
    mock_cache = MagicMock(spec=RedisCache)

    async def _get(*_a: object, **_kw: object) -> object:
        return get_return

    async def _set(*_a: object, **_kw: object) -> None:
        return

    async def _delete(*_a: object, **_kw: object) -> None:
        if delete_side_effect is not None:
            raise delete_side_effect

    async def _close() -> None:
        return

    mock_cache.get = _get
    mock_cache.set = _set
    mock_cache.delete = _delete
    mock_cache.close = _close
    return mock_cache


class TestCachedSyncInvalidateError:
    """Tests for cached_sync invalidate error handling."""

    def test_invalidate_logs_warning_on_error(self) -> None:
        """Should log warning when cache delete fails."""
        mock_cache = _make_sync_mock_cache(
            delete_side_effect=CacheOperationError("Delete failed"),
        )

        @cached_sync(key_prefix="test", cache_factory=lambda: mock_cache)
        def test_func(x: int) -> int:
            return x * 2

        test_func(5)

        with patch("nohiki_redis_utils.decorators.logger") as mock_logger:
            test_func.invalidate(5)

            mock_logger.warning.assert_called_once()


class TestCachedSyncInvalidateSuccess:
    """Tests for cached_sync invalidate success path."""

    def test_invalidate_logs_debug_on_success(self) -> None:
        """Should log debug when cache delete succeeds."""
        mock_cache = _make_sync_mock_cache()

        @cached_sync(key_prefix="test", cache_factory=lambda: mock_cache)
        def test_func(x: int) -> int:
            return x * 2

        test_func(5)

        with patch("nohiki_redis_utils.decorators.logger") as mock_logger:
            test_func.invalidate(5)

            mock_logger.debug.assert_called()


class TestCachedSyncBypassCache:
    """Tests for cached_sync bypass_cache (line 242)."""

    def test_bypasses_cache_when_flag_set(self) -> None:
        """Should bypass cache when bypass_cache=True (line 242)."""
        get_called = False

        async def _tracking_get(*_a: object, **_kw: object) -> str:
            nonlocal get_called
            get_called = True
            return "cached_value"

        mock_cache = _make_sync_mock_cache(get_return="cached_value")
        mock_cache.get = _tracking_get

        call_count = 0

        @cached_sync(key_prefix="test", cache_factory=lambda: mock_cache)
        def test_func(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result = test_func(5, bypass_cache=True)

        assert result == 10
        assert call_count == 1
        assert not get_called

"""Caching decorators for async and sync functions."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

from nohiki_observability import get_logger

from .helpers import make_cache_key, sanitize_cache_value

if TYPE_CHECKING:
    from .redis_cache import RedisCache


class _AsyncFunc[**P, T](Protocol):
    """Protocol for async functions with __name__ attribute."""

    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T]: ...


class _SyncFunc[**P, T](Protocol):
    """Protocol for sync functions with __name__ attribute."""

    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T: ...


class CachedAsyncFunction[**P, T](Protocol):
    """Protocol for async cached functions with invalidate method."""

    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Awaitable[T]:
        """Execute the cached async function."""
        ...

    async def invalidate(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Invalidate the cached result for the given arguments."""
        ...


class CachedSyncFunction[**P, T](Protocol):
    """Protocol for sync cached functions with invalidate method."""

    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute the cached sync function."""
        ...

    def invalidate(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Invalidate the cached result for the given arguments."""
        ...


logger = get_logger(__name__)


class CacheOperationError(Exception):
    """Raised when cache operations fail."""


async def _try_cache_get(cache: RedisCache, key: str, function_name: str) -> object:
    """Attempt to get value from cache, handling exceptions gracefully."""
    try:
        cached_value = await cache.get(key)
        if cached_value is not None:
            logger.debug("Cache hit", function=function_name, key=key)
            return cached_value
    except CacheOperationError as e:
        logger.warning("Cache get failed", function=function_name, key=key, error=str(e))
    return None


async def _try_cache_set(
    cache: RedisCache,
    key: str,
    result: object,
    ttl: int | None,
    function_name: str,
) -> None:
    """Attempt to set value in cache, handling exceptions gracefully."""
    try:
        sanitized_result = sanitize_cache_value(result)
        await cache.set(key, sanitized_result, ttl=ttl)
        logger.debug("Cache set", function=function_name, key=key, ttl=ttl)
    except CacheOperationError as e:
        logger.warning("Cache set failed", function=function_name, key=key, error=str(e))


def _get_cache_key(
    key_prefix: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    key_builder: Callable[[str, tuple[Any, ...], dict[str, Any]], str] | None,
) -> str:
    """Get cache key using either custom builder or default logic."""
    if key_builder:
        return key_builder(key_prefix, args, kwargs)
    return make_cache_key(key_prefix, *args, **kwargs)


def _should_bypass_cache(kwargs: dict[str, Any], skip_kwarg: str) -> bool:
    """Check if cache should be bypassed."""
    return bool(kwargs.pop(skip_kwarg, False))


def cached[**P, T](
    key_prefix: str = "",
    ttl: int | None = None,
    *,
    cache_factory: Callable[[], RedisCache],
    skip_kwarg: str = "bypass_cache",
    key_builder: Callable[[str, tuple[Any, ...], dict[str, Any]], str] | None = None,
) -> Callable[[_AsyncFunc[P, T]], CachedAsyncFunction[P, T]]:
    """Read-through async cache decorator.

    Args:
        key_prefix: First segment in the cache key (e.g., "job", "user")
        ttl: Time to live in seconds (None = no expiry)
        cache_factory: Factory to obtain a RedisCache instance
        skip_kwarg: Keyword argument name to bypass cache
        key_builder: Custom cache key builder function

    """

    def decorator(func: _AsyncFunc[P, T]) -> CachedAsyncFunction[P, T]:
        func_name = func.__name__

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if _should_bypass_cache(kwargs, skip_kwarg):
                return await func(*args, **kwargs)

            cache = cache_factory()
            cache_key = _get_cache_key(key_prefix, args, kwargs, key_builder)

            cached_value = await _try_cache_get(cache, cache_key, func_name)
            if cached_value is not None:
                return cast(T, cached_value)

            result = await func(*args, **kwargs)
            await _try_cache_set(cache, cache_key, result, ttl, func_name)

            return result

        async def invalidate(*args: P.args, **kwargs: P.kwargs) -> None:
            """Manually invalidate cache entry for specific arguments."""
            cache = cache_factory()
            cache_key = _get_cache_key(key_prefix, args, kwargs, key_builder)

            try:
                await cache.delete(cache_key)
                logger.debug("Cache invalidated", function=func_name, key=cache_key)
            except CacheOperationError as e:
                logger.warning(
                    "Cache invalidation failed",
                    function=func_name,
                    key=cache_key,
                    error=str(e),
                )

        cast(Any, wrapper).invalidate = invalidate
        return cast(CachedAsyncFunction[P, T], wrapper)

    return decorator


def _run_async_with_cache[R](
    cache_factory: Callable[[], RedisCache],
    operation: Callable[[RedisCache], Awaitable[R]],
) -> R:
    """Run async cache operation via asyncio.run() for proper lifecycle cleanup."""

    async def _run() -> R:
        cache = cache_factory()
        try:
            return await operation(cache)
        finally:
            await cache.close()

    return asyncio.run(_run())


def _sync_cache_get(
    cache_factory: Callable[[], RedisCache],
    cache_key: str,
    function_name: str,
) -> object:
    """Get value from cache for sync functions."""
    return _run_async_with_cache(
        cache_factory,
        lambda cache: _try_cache_get(cache, cache_key, function_name),
    )


def _sync_cache_set(
    cache_factory: Callable[[], RedisCache],
    cache_key: str,
    result: object,
    ttl: int | None,
    function_name: str,
) -> None:
    """Set value in cache for sync functions."""
    _run_async_with_cache(
        cache_factory,
        lambda cache: _try_cache_set(cache, cache_key, result, ttl, function_name),
    )


def _sync_cache_delete(
    cache_factory: Callable[[], RedisCache],
    cache_key: str,
    function_name: str,
) -> None:
    """Delete value from cache for sync functions."""

    async def delete_and_log(cache: RedisCache) -> None:
        await cache.delete(cache_key)
        logger.debug("Cache invalidated", function=function_name, key=cache_key)

    _run_async_with_cache(cache_factory, delete_and_log)


def cached_sync[**P, T](
    key_prefix: str = "",
    ttl: int | None = None,
    *,
    cache_factory: Callable[[], RedisCache],
    skip_kwarg: str = "bypass_cache",
    key_builder: Callable[[str, tuple[Any, ...], dict[str, Any]], str] | None = None,
) -> Callable[[_SyncFunc[P, T]], CachedSyncFunction[P, T]]:
    """Read-through sync cache decorator.

    Args:
        key_prefix: First segment in the cache key (e.g., "job", "user")
        ttl: Time to live in seconds (None = no expiry)
        cache_factory: Factory to obtain a RedisCache instance
        skip_kwarg: Keyword argument name to bypass cache
        key_builder: Custom cache key builder function

    """

    def decorator(func: _SyncFunc[P, T]) -> CachedSyncFunction[P, T]:
        func_name = func.__name__

        def get_cache() -> RedisCache:
            return cache_factory()

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if _should_bypass_cache(kwargs, skip_kwarg):
                return func(*args, **kwargs)

            cache_key = _get_cache_key(key_prefix, args, kwargs, key_builder)

            cached_value = _sync_cache_get(get_cache, cache_key, func_name)
            if cached_value is not None:
                return cast(T, cached_value)

            result = func(*args, **kwargs)
            _sync_cache_set(get_cache, cache_key, result, ttl, func_name)

            return result

        def invalidate(*args: P.args, **kwargs: P.kwargs) -> None:
            """Manually invalidate cache entry for specific arguments."""
            cache_key = _get_cache_key(key_prefix, args, kwargs, key_builder)

            try:
                _sync_cache_delete(get_cache, cache_key, func_name)
            except CacheOperationError as e:
                logger.warning(
                    "Cache invalidation failed",
                    function=func_name,
                    key=cache_key,
                    error=str(e),
                )

        cast(Any, wrapper).invalidate = invalidate
        return cast(CachedSyncFunction[P, T], wrapper)

    return decorator

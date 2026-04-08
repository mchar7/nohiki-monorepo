"""Tests for caching decorators."""
# mypy: disallow_untyped_decorators=false

from __future__ import annotations

import asyncio
import uuid

import pytest
from nohiki_redis_utils.decorators import cached, cached_sync

# Test constants to avoid magic numbers
EXPECTED_CALL_COUNT_FIRST = 1
EXPECTED_CALL_COUNT_SECOND = 2


class SimpleMemoryCache:
    """Simple in-memory cache for testing decorators."""

    def __init__(self) -> None:
        """Initialize empty cache."""
        self._data: dict[str, object] = {}

    async def get(self, key: str) -> object:
        """Get value from cache."""
        await self._ensure_async()
        return self._data.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None) -> None:
        """Set value in cache."""
        await self._ensure_async()
        _ = ttl  # TTL is intentionally ignored in memory cache
        self._data[key] = value

    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        await self._ensure_async()
        self._data.pop(key, None)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        await self._ensure_async()
        return key in self._data

    async def setnx(self, key: str, value: object, ttl: int | None = None) -> bool:
        """Set if not exists."""
        await self._ensure_async()
        _ = ttl  # TTL is intentionally ignored in memory cache
        if key in self._data:
            return False
        self._data[key] = value
        return True

    async def close(self) -> None:
        """Close cache (no-op for memory cache)."""
        await self._ensure_async()

    @staticmethod
    async def _ensure_async() -> None:
        """Yield control to verify async execution path."""
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cached_decorator_basic() -> None:
    """Test basic caching functionality."""
    call_count = 0
    # Use unique prefix to avoid cross-test pollution
    prefix = f"test_basic_{uuid.uuid4().hex[:8]}"

    cache = SimpleMemoryCache()

    @cached(key_prefix=prefix, ttl=60, cache_factory=lambda: cache)
    async def expensive_function(arg1: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{arg1}"

    # First call should execute function
    result1 = await expensive_function("foo")
    assert result1 == "result-foo"
    assert call_count == EXPECTED_CALL_COUNT_FIRST

    # Second call should use cache
    result2 = await expensive_function("foo")
    assert result2 == "result-foo"
    assert call_count == EXPECTED_CALL_COUNT_FIRST  # Should not increment

    # Different argument should execute function again
    result3 = await expensive_function("bar")
    assert result3 == "result-bar"
    assert call_count == EXPECTED_CALL_COUNT_SECOND


@pytest.mark.asyncio
async def test_cached_decorator_bypass() -> None:
    """Test cache bypass functionality."""
    call_count = 0
    prefix = f"test_bypass_{uuid.uuid4().hex[:8]}"

    cache = SimpleMemoryCache()

    @cached(key_prefix=prefix, ttl=60, cache_factory=lambda: cache)
    async def expensive_function(arg1: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{arg1}"

    # First call
    await expensive_function("foo")
    assert call_count == EXPECTED_CALL_COUNT_FIRST

    await expensive_function("foo", bypass_cache=True)
    assert call_count == EXPECTED_CALL_COUNT_SECOND


@pytest.mark.asyncio
async def test_cached_decorator_invalidation() -> None:
    """Test cache invalidation."""
    call_count = 0
    prefix = f"test_invalidation_{uuid.uuid4().hex[:8]}"

    cache = SimpleMemoryCache()

    @cached(key_prefix=prefix, ttl=60, cache_factory=lambda: cache)
    async def expensive_function(arg1: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{arg1}"

    # First call
    await expensive_function("foo")
    assert call_count == EXPECTED_CALL_COUNT_FIRST

    # Invalidate - use getattr to access dynamically added method
    invalidate_fn = expensive_function.invalidate
    await invalidate_fn("foo")

    # Next call should execute function again
    await expensive_function("foo")
    assert call_count == EXPECTED_CALL_COUNT_SECOND


def test_cached_sync_decorator() -> None:
    """Test synchronous caching decorator."""
    call_count = 0
    prefix = f"test_sync_{uuid.uuid4().hex[:8]}"

    cache = SimpleMemoryCache()

    @cached_sync(key_prefix=prefix, ttl=60, cache_factory=lambda: cache)
    def expensive_function(arg1: str) -> str:
        nonlocal call_count
        call_count += 1
        return f"result-{arg1}"

    # First call should execute function
    result1 = expensive_function("foo")
    assert result1 == "result-foo"
    assert call_count == EXPECTED_CALL_COUNT_FIRST

    # Second call should use cache
    result2 = expensive_function("foo")
    assert result2 == "result-foo"
    assert call_count == EXPECTED_CALL_COUNT_FIRST

"""Tests for nohiki-redis-utils testing module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from nohiki_redis_utils.redis_cache import RedisCache
    from redis.asyncio import Redis


class TestRedisContainerFixture:
    """Tests for redis_container fixture."""

    def test_redis_container_returns_connection_url(self, redis_container: str) -> None:
        """Verify redis_container fixture returns a valid connection URL."""
        assert redis_container.startswith("redis://")
        assert ":" in redis_container


class TestRedisClientFixture:
    """Tests for redis_client fixture."""

    @pytest.mark.asyncio
    async def test_redis_client_is_connected(self, redis_client: Redis) -> None:
        """Verify redis_client fixture provides a connected client."""
        await redis_client.ping()

    @pytest.mark.asyncio
    async def test_redis_client_can_set_and_get(self, redis_client: Redis) -> None:
        """Verify redis_client can perform basic operations."""
        await redis_client.set("test_key", "test_value")
        result = await redis_client.get("test_key")
        assert result == b"test_value"


class TestRedisCacheFixture:
    """Tests for redis_cache fixture."""

    @pytest.mark.asyncio
    async def test_redis_cache_is_functional(self, redis_cache: RedisCache) -> None:
        """Verify redis_cache fixture provides a functional cache."""
        await redis_cache.set("cache_key", "cache_value")
        result = await redis_cache.get("cache_key")
        assert result == "cache_value"

    @pytest.mark.asyncio
    async def test_redis_cache_binary_operations(self, redis_cache: RedisCache) -> None:
        """Verify redis_cache supports binary operations."""
        test_data = b"binary\x00data"
        await redis_cache.set_bytes("binary_key", test_data)
        result = await redis_cache.get_bytes("binary_key")
        assert result == test_data

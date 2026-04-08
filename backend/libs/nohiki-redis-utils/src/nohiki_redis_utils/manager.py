"""Generic cache manager for consistent cache instance management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_observability import get_logger

if TYPE_CHECKING:
    from .redis_cache import RedisCache

from .factory import create_cache

logger = get_logger(__name__)


class CacheManager[T]:
    """Manages cache instances with service isolation."""

    def __init__(self, service_name: str, *, redis_url: str) -> None:
        """Initialize cache manager for a specific service."""
        self.service_name = service_name
        self.redis_url = redis_url
        self._cache_instance: RedisCache | None = None

    def get_cache(self) -> RedisCache:
        """Get the cache instance for this service."""
        if self._cache_instance is None:
            self._cache_instance = create_cache(self.service_name, redis_url=self.redis_url)
            logger.debug("Created cache instance", service=self.service_name)

        return self._cache_instance

    async def get(self, key: str) -> object:
        """Get value from cache."""
        cache = self.get_cache()
        return await cache.get(key)

    async def set(self, key: str, value: object, ttl: int | None = None) -> None:
        """Set value in cache."""
        cache = self.get_cache()
        await cache.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        """Delete value from cache."""
        cache = self.get_cache()
        await cache.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        cache = self.get_cache()
        return await cache.exists(key)

    def reset_for_testing(self) -> None:
        """Reset cache instance for testing purposes."""
        self._cache_instance = None
        logger.debug("Reset cache instance", service=self.service_name)

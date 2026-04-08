"""Cache factory for creating cache instances."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from nohiki_observability import get_logger

from .redis_cache import RedisCache

logger = get_logger(__name__)


class CacheCreationError(Exception):
    """Raised when cache creation fails."""


class CacheFactory:
    """Factory for per-service cache instances.

    The configured DSN is used as-is. Isolation comes from the
    ``{service_name}:`` key prefix applied by ``RedisCache._make_key``.
    """

    _instances: ClassVar[dict[str, RedisCache]] = {}
    _instance_loop_ids: ClassVar[dict[str, int | None]] = {}
    _pending_closes: ClassVar[set[asyncio.Task[None]]] = set()

    @classmethod
    def clear_instances(cls) -> None:
        """Clear all cached instances. Useful for testing."""
        cls._instances.clear()
        cls._instance_loop_ids.clear()
        for task in cls._pending_closes:
            task.cancel()
        cls._pending_closes.clear()

    @classmethod
    async def close_all(cls) -> None:
        """Close all cached instances and clear them. Use for proper cleanup."""
        for cache in cls._instances.values():
            try:
                await cache.close()
            except RuntimeError as e:
                # Event loop may be closed for caches created in different loops
                if "Event loop is closed" not in str(e):
                    raise
        if cls._pending_closes:
            # gather() rejects tasks bound to another loop; those can only be dropped
            current_loop = asyncio.get_running_loop()
            same_loop = [t for t in cls._pending_closes if t.get_loop() is current_loop]
            if same_loop:
                await asyncio.gather(*same_loop, return_exceptions=True)
            cls._pending_closes.clear()
        cls._instances.clear()
        cls._instance_loop_ids.clear()

    @classmethod
    def create_cache(cls, service_name: str, *, redis_url: str) -> RedisCache:
        """Create (or reuse) the Redis cache instance for a service.

        Args:
            service_name: Name of the service requesting the cache; used as
                the key prefix for isolation.
            redis_url: Redis DSN, used verbatim.

        Returns:
            Cache instance bound to the current event loop.

        """
        # Get current event loop ID to detect loop changes
        current_loop_id = cls._get_current_loop_id()

        if service_name in cls._instances:
            cached_loop_id = cls._instance_loop_ids.get(service_name)
            # Reuse if same loop or if we can't determine loop (no running loop)
            if current_loop_id is None or cached_loop_id == current_loop_id:
                return cls._instances[service_name]
            # Different loop: close the evicted instance instead of dropping it
            logger.debug(
                "Creating fresh cache for different event loop",
                service=service_name,
                cached_loop_id=cached_loop_id,
                current_loop_id=current_loop_id,
            )
            cls._schedule_close(cls._instances.pop(service_name))

        cache_instance = cls._create_redis_cache(service_name, redis_url)
        cls._instances[service_name] = cache_instance
        cls._instance_loop_ids[service_name] = current_loop_id
        return cache_instance

    @classmethod
    def _schedule_close(cls, cache: RedisCache) -> None:
        """Best-effort close for an instance evicted by an event-loop change."""

        async def _close() -> None:
            try:
                await cache.close()
            except RuntimeError as e:
                if "Event loop is closed" not in str(e):
                    logger.warning("Failed to close evicted cache", error=str(e))

        task = asyncio.get_running_loop().create_task(_close())
        cls._pending_closes.add(task)
        task.add_done_callback(cls._pending_closes.discard)

    @classmethod
    def _get_current_loop_id(cls) -> int | None:
        """Get current event loop ID, or None if no running loop."""
        try:
            loop = asyncio.get_running_loop()
            return id(loop)
        except RuntimeError:
            return None

    @classmethod
    def _create_redis_cache(cls, service_name: str, redis_url: str) -> RedisCache:
        """Create Redis cache instance with proper error handling."""
        try:
            cache_instance = RedisCache(redis_url, service_name)
            logger.info("Created Redis cache instance", service=service_name)
        except CacheCreationError:
            logger.exception("Failed to create Redis cache", service=service_name)
            msg = "Failed to create Redis cache. Provide a valid redis_url from your service config"
            raise CacheCreationError(msg) from None

        return cache_instance


def create_cache(service_name: str, *, redis_url: str) -> RedisCache:
    """Create cache instance for a specific service."""
    return CacheFactory.create_cache(service_name, redis_url=redis_url)

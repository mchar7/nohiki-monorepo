"""Redis cache utilities for job-correlation-evaluation-service."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from job_correlation_evaluation_service.core.config import get_settings
from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, create_cache

if TYPE_CHECKING:
    from job_correlation_evaluation_service.core.config import Settings

logger = get_logger(__name__)


class _CacheHolder:
    """Container for module-level cache reference."""

    instance: RedisCache | None = None


@lru_cache(maxsize=1)
def get_cache(settings: Settings | None = None) -> RedisCache:
    """Get the Redis cache client.

    Lazily creates and caches the Redis connection.

    Args:
        settings: Optional settings instance. Uses get_settings() if not provided.

    Returns:
        Configured RedisCache instance.

    """
    if _CacheHolder.instance is not None:
        return _CacheHolder.instance

    if settings is None:
        settings = get_settings()

    _CacheHolder.instance = create_cache(
        settings.service_name,
        redis_url=settings.redis.connection_string,
    )
    logger.info("Redis cache ready", service=settings.service_name)
    return _CacheHolder.instance


async def close_cache() -> None:
    """Close and evict the Redis cache connection."""
    instance = _CacheHolder.instance
    try:
        if instance is not None:
            await instance.close()
            logger.debug("Redis cache closed")
    except RuntimeError as exc:
        if str(exc) != "Event loop is closed":
            raise
        logger.warning("Discarding Redis cache created by a closed event loop")
    finally:
        _CacheHolder.instance = None
        get_cache.cache_clear()


def reset_cache() -> None:
    """Reset cache instance (for testing)."""
    _CacheHolder.instance = None
    get_cache.cache_clear()

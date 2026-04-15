"""Redis-based deduplication service for job-ingest-discovery-service.

Uses content hash to identify duplicate listings within a configurable TTL window.
No database dependency - purely Redis-backed.
"""

from __future__ import annotations

from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, create_cache

from job_ingest_discovery_service.core.config import get_settings

logger = get_logger(__name__)

_DEDUP_PREFIX = "dedup"


def _get_cache() -> RedisCache:
    """Get Redis cache client lazily."""
    settings = get_settings()
    return create_cache(settings.service_name, redis_url=settings.redis.connection_string)


class _DedupServiceHolder:
    """Singleton holder for DedupService."""

    instance: DedupService | None = None


class DedupService:
    """Redis-based deduplication using content hash."""

    def __init__(self) -> None:
        """Initialize dedup service with Redis cache."""
        settings = get_settings()
        self._cache = _get_cache()
        self._ttl = settings.caching.dedup_ttl_seconds

    async def is_duplicate(self, content_hash: str) -> bool:
        """Check if content hash was seen recently."""
        key = f"{_DEDUP_PREFIX}:hash:{content_hash}"
        return await self._cache.exists(key)

    async def mark_seen(self, content_hash: str) -> None:
        """Mark content hash as seen."""
        key = f"{_DEDUP_PREFIX}:hash:{content_hash}"
        await self._cache.set(key, "1", ttl=self._ttl)


def get_dedup_service() -> DedupService:
    """Get singleton dedup service instance."""
    if _DedupServiceHolder.instance is None:
        _DedupServiceHolder.instance = DedupService()
    return _DedupServiceHolder.instance

"""Async cache manager using nohiki-redis-utils for document content caching."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel
from nohiki_observability import get_logger
from nohiki_redis_utils import CacheFactory, RedisCache

from doc_process_service.cache.keys import CacheKeyBuilder
from doc_process_service.models.domain import ProcessingOptions

if TYPE_CHECKING:
    from doc_process_service.core.config import Settings

logger = get_logger(__name__)


def compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash for cache key generation."""
    return hashlib.sha256(content).hexdigest()


def get_cache(settings: Settings) -> RedisCache:
    """Get or create cache instance via CacheFactory."""
    return CacheFactory.create_cache(
        settings.service_name,
        redis_url=settings.redis.connection_string,
    )


class CacheManager:
    """Async cache manager with two-tier content-addressable storage using nohiki-redis-utils."""

    __slots__ = ("_cache", "_keys", "_processed_ttl", "_raw_ttl")

    def __init__(
        self,
        cache: RedisCache,
        raw_ttl: int,
        processed_ttl: int,
        keys: CacheKeyBuilder | None = None,
    ) -> None:
        """Initialize cache manager.

        Args:
            cache: RedisCache instance from nohiki-redis-utils.
            raw_ttl: TTL for raw content in seconds.
            processed_ttl: TTL for processed content in seconds.
            keys: Key builder (uses default if not provided).

        """
        self._cache = cache
        self._raw_ttl = raw_ttl
        self._processed_ttl = processed_ttl
        self._keys = keys or CacheKeyBuilder()

    async def get_raw(self, content_id: str) -> bytes | None:
        """Retrieve cached raw bytes by content_id."""
        return await self._cache.get_bytes(self._keys.raw_key(content_id))

    async def set_raw(self, content_id: str, content: bytes, checksum: str) -> bool:
        """Cache raw bytes with associated checksum."""
        try:
            await self._cache.set_bytes(self._keys.raw_key(content_id), content, ttl=self._raw_ttl)
            await self._cache.set(self._keys.checksum_key(content_id), checksum, ttl=self._raw_ttl)
        except OSError:
            logger.warning("Failed to cache raw content", content_id=content_id, exc_info=True)
            return False
        return True

    async def get_processed(self, content_hash: str, options: ProcessingOptions) -> ProcessedDocumentSnapshot | None:
        """Retrieve processed content at or above requested level."""
        requested_level = options.level

        for level in ProcessingLevel:
            if level < requested_level:
                continue
            key = self._keys.processed_key(content_hash, level.name.lower())
            if (data := await self._cache.get_bytes(key)) and (snapshot := self._deserialize_snapshot(data)):
                return snapshot

        return None

    async def set_processed(self, content_hash: str, snapshot: ProcessedDocumentSnapshot) -> bool:
        """Cache processed content by hash."""
        key = self._keys.processed_key(content_hash, snapshot.level.name.lower())
        try:
            await self._cache.set_bytes(key, self._serialize_snapshot(snapshot), ttl=self._processed_ttl)
        except OSError:
            logger.warning("Failed to cache processed content", content_hash=content_hash, exc_info=True)
            return False
        return True

    async def get_checksum(self, content_id: str) -> str | None:
        """Retrieve cached checksum for content_id."""
        result = await self._cache.get(self._keys.checksum_key(content_id))
        if isinstance(result, str):
            return result
        return None

    async def has_content_changed(self, content_id: str, new_checksum: str) -> bool:
        """Check if content has changed since caching."""
        cached = await self.get_checksum(content_id)
        if cached is None:
            return False
        return cached != new_checksum

    async def invalidate(self, content_id: str) -> int:
        """Invalidate all cached data for content_id. Returns count of deleted keys."""
        keys = [self._keys.raw_key(content_id), self._keys.checksum_key(content_id)]
        deleted = 0
        for key in keys:
            try:
                await self._cache.delete(key)
                deleted += 1
            except OSError:
                logger.debug("Failed to delete cache key", key=key, exc_info=True)
        return deleted

    async def get_highest_level(self, content_hash: str) -> ProcessingLevel | None:
        """Find highest cached processing level for a content hash."""
        for level in reversed(list(ProcessingLevel)):
            key = self._keys.processed_key(content_hash, level.name.lower())
            if await self._cache.exists(key):
                return level
        return None

    def _serialize_snapshot(self, snapshot: ProcessedDocumentSnapshot) -> bytes:
        """Serialize ProcessedDocumentSnapshot to JSON bytes using betterproto2."""
        return snapshot.to_json().encode()

    def _deserialize_snapshot(self, data: bytes) -> ProcessedDocumentSnapshot | None:
        """Deserialize ProcessedDocumentSnapshot from JSON bytes using betterproto2."""
        try:
            return ProcessedDocumentSnapshot.from_json(data.decode())
        except ValueError, TypeError, KeyError:
            logger.warning("Failed to deserialize snapshot", exc_info=True)
            return None

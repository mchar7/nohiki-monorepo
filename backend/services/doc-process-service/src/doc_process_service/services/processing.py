"""Document processing service for ECST event-driven architecture."""

from __future__ import annotations

import asyncio
import importlib
from typing import TYPE_CHECKING, cast

from nohiki.doc.process.v1 import ProcessedDocumentSnapshot
from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache

from doc_process_service.cache import CacheManager, compute_content_hash
from doc_process_service.cache.keys import CacheKeyBuilder
from doc_process_service.cache.manager import get_cache
from doc_process_service.models.domain import ProcessingOptions, ProcessingResult

if TYPE_CHECKING:
    from doc_process_service.core.config import Settings
    from doc_process_service.providers.docling import DoclingClient, DoclingClientConfig

logger = get_logger(__name__)


class ProcessingService:
    """Document processing service for ECST architecture.

    Orchestrates document processing via Docling provider with Redis caching.
    Designed for stateless event-driven processing where each request is
    independent and results are published to Kafka.
    """

    __slots__ = ("_cache", "_client", "_settings")

    def __init__(
        self,
        settings: Settings,
        cache: RedisCache | None = None,
    ) -> None:
        """Initialize processing service.

        Args:
            settings: Service configuration.
            cache: Optional RedisCache instance (uses factory if not provided).

        """
        self._settings = settings
        self._client = self._create_docling_client(settings)
        self._cache = self._create_cache_manager(settings, cache)

    def _create_docling_client(self, settings: Settings) -> DoclingClient:
        """Create Docling client from settings."""
        docling = importlib.import_module("doc_process_service.providers.docling")
        client_type = cast("type[DoclingClient]", docling.DoclingClient)
        config_type = cast("type[DoclingClientConfig]", docling.DoclingClientConfig)
        config = config_type.from_settings(settings.docling, settings.vlm)
        return client_type(config)

    def _create_cache_manager(
        self,
        settings: Settings,
        cache: RedisCache | None,
    ) -> CacheManager:
        """Create cache manager from settings."""
        if cache is None:
            cache = get_cache(settings)
        keys = CacheKeyBuilder(prefix=settings.cache.key_prefix)
        return CacheManager(
            cache=cache,
            raw_ttl=settings.cache.raw_ttl_seconds,
            processed_ttl=settings.cache.processed_ttl_seconds,
            keys=keys,
        )

    def is_available(self) -> bool:
        """Check if processing provider is ready."""
        return self._client.is_available()

    async def process(
        self,
        content_id: str,
        raw_content: bytes,
        options: ProcessingOptions | None = None,
    ) -> ProcessingResult:
        """Process document content.

        Args:
            content_id: Opaque identifier for caching.
            raw_content: Raw document bytes.
            options: Processing configuration.

        Returns:
            ProcessingResult with extracted content or error details.

        """
        options = options or ProcessingOptions()
        if not raw_content:
            return ProcessingResult(error="Document is empty")
        if len(raw_content) > self._settings.docling.max_document_bytes:
            return ProcessingResult(error="Document exceeds the configured size limit")

        content_hash = compute_content_hash(raw_content)

        if cached := await self._cache.get_processed(content_hash, options):
            cached.content_id = content_id
            cached.content_hash = content_hash
            logger.debug("Cache hit", content_id=content_id)
            return ProcessingResult(content=cached)

        await self._cache.set_raw(content_id, raw_content, content_hash)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            self._client.process,
            raw_content,
            content_id,
            options,
        )

        if result.is_cacheable and result.content:
            await self._cache.set_processed(content_hash, result.content)

        return result

    async def get_cached(
        self,
        content_hash: str,
        options: ProcessingOptions | None = None,
    ) -> ProcessedDocumentSnapshot | None:
        """Retrieve cached content if available at sufficient level.

        Args:
            content_hash: SHA-256 hash of raw content.
            options: Desired processing level.

        Returns:
            ProcessedContent if cached, None otherwise.

        """
        options = options or ProcessingOptions()
        return await self._cache.get_processed(content_hash, options)

    async def invalidate(self, content_id: str) -> int:
        """Invalidate cached content. Returns count of deleted entries."""
        return await self._cache.invalidate(content_id)

    @property
    def cache(self) -> CacheManager:
        """Access cache manager for direct operations."""
        return self._cache

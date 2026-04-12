"""Tests for doc_process_service.services.processing module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
from doc_process_service.cache import CacheManager
from doc_process_service.core.config import Settings
from doc_process_service.models.domain import ProcessingOptions, ProcessingResult
from doc_process_service.providers.docling import DoclingClient
from doc_process_service.services.processing import ProcessingService
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel


@pytest.fixture
def service_settings() -> Settings:
    """Create service settings for testing."""
    return Settings()


@pytest.fixture
def mock_docling_client() -> MagicMock:
    """Create mock DoclingClient."""
    mock = create_autospec(DoclingClient, instance=True)
    mock.name = "docling"
    mock.is_available.return_value = True
    return mock


@pytest.fixture
def mock_cache_manager() -> MagicMock:
    """Create mock CacheManager."""
    mock = create_autospec(CacheManager, instance=True)
    mock.is_enabled = True
    return mock


@pytest.fixture
def processing_service(
    service_settings: Settings,
    mock_docling_client: MagicMock,
    mock_cache_manager: MagicMock,
) -> ProcessingService:
    """Create ProcessingService with mocked dependencies."""
    service = ProcessingService.__new__(ProcessingService)
    object.__setattr__(service, "_settings", service_settings)
    object.__setattr__(service, "_client", mock_docling_client)
    object.__setattr__(service, "_cache", mock_cache_manager)
    return service


@pytest.fixture
def real_processing_service(service_settings: Settings) -> ProcessingService:
    """Create real ProcessingService for initialization tests."""
    return ProcessingService(service_settings, cache=None)


class TestProcessingServiceInit:
    """Tests for ProcessingService initialization."""

    def test_init_creates_docling_client(
        self,
        real_processing_service: ProcessingService,
    ) -> None:
        """Test initialization creates Docling client."""
        assert real_processing_service._client is not None
        assert real_processing_service._client.name == "docling"

    def test_init_creates_cache_manager(
        self,
        real_processing_service: ProcessingService,
    ) -> None:
        """Test initialization creates cache manager."""
        assert real_processing_service._cache is not None
        assert isinstance(real_processing_service._cache, CacheManager)

    def test_cache_property(self, real_processing_service: ProcessingService) -> None:
        """Test cache property returns cache manager."""
        assert real_processing_service.cache is real_processing_service._cache


class TestProcessingServiceIsAvailable:
    """Tests for is_available method."""

    def test_is_available_returns_true(
        self,
        processing_service: ProcessingService,
        mock_docling_client: MagicMock,
    ) -> None:
        """Test is_available returns True when client available."""
        mock_docling_client.is_available.return_value = True
        assert processing_service.is_available() is True

    def test_is_available_returns_false(
        self,
        processing_service: ProcessingService,
        mock_docling_client: MagicMock,
    ) -> None:
        """Test is_available returns False when client unavailable."""
        mock_docling_client.is_available.return_value = False
        assert processing_service.is_available() is False


class TestProcessingServiceProcess:
    """Tests for async process method."""

    @pytest.mark.asyncio
    async def test_process_returns_cached_content(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Test process returns cached content when available."""
        cached_content = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hash123",
            level=ProcessingLevel.TABLES,
            markdown="# Cached",
        )
        mock_cache_manager.get_processed = AsyncMock(return_value=cached_content)

        result = await processing_service.process("test_id", b"content", ProcessingOptions())

        assert result.success
        assert result.content == cached_content

    @pytest.mark.asyncio
    async def test_process_calls_provider_on_cache_miss(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
        mock_docling_client: MagicMock,
    ) -> None:
        """Test process calls provider when cache miss."""
        processed_content = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hash456",
            level=ProcessingLevel.TABLES,
            markdown="# Processed",
        )
        provider_result = ProcessingResult(content=processed_content)

        mock_cache_manager.get_processed = AsyncMock(return_value=None)
        mock_cache_manager.set_raw = AsyncMock(return_value=True)
        mock_cache_manager.set_processed = AsyncMock(return_value=True)
        mock_docling_client.process = MagicMock(return_value=provider_result)

        result = await processing_service.process("test_id", b"content", ProcessingOptions())

        assert result.success
        assert result.content == processed_content
        mock_docling_client.process.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_uses_default_options(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
        mock_docling_client: MagicMock,
    ) -> None:
        """Test process uses default options when not provided."""
        processed_content = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hash789",
            level=ProcessingLevel.TABLES,
            markdown="# Processed",
        )
        provider_result = ProcessingResult(content=processed_content)

        mock_cache_manager.get_processed = AsyncMock(return_value=None)
        mock_cache_manager.set_raw = AsyncMock(return_value=True)
        mock_cache_manager.set_processed = AsyncMock(return_value=True)
        mock_docling_client.process = MagicMock(return_value=provider_result)

        result = await processing_service.process("test_id", b"content", None)

        assert result.success

    @pytest.mark.asyncio
    async def test_process_caches_successful_result(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
        mock_docling_client: MagicMock,
    ) -> None:
        """Test process caches successful, non-empty result."""
        processed_content = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hashabc",
            level=ProcessingLevel.TABLES,
            markdown="# Processed",
        )
        provider_result = ProcessingResult(content=processed_content)

        mock_cache_manager.get_processed = AsyncMock(return_value=None)
        mock_cache_manager.set_raw = AsyncMock(return_value=True)
        mock_cache_manager.set_processed = AsyncMock(return_value=True)
        mock_docling_client.process = MagicMock(return_value=provider_result)

        await processing_service.process("test_id", b"content")

        mock_cache_manager.set_raw.assert_called_once()
        mock_cache_manager.set_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_does_not_cache_error_result(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
        mock_docling_client: MagicMock,
    ) -> None:
        """Test process does not cache error result."""
        provider_result = ProcessingResult(error="Processing failed")

        mock_cache_manager.get_processed = AsyncMock(return_value=None)
        mock_cache_manager.set_raw = AsyncMock(return_value=True)
        mock_docling_client.process = MagicMock(return_value=provider_result)

        await processing_service.process("test_id", b"content")

        mock_cache_manager.set_processed.assert_not_called()


class TestProcessingServiceGetCached:
    """Tests for async get_cached method."""

    @pytest.mark.asyncio
    async def test_get_cached_returns_content(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Test get_cached returns cached content."""
        cached_content = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hash123",
            level=ProcessingLevel.TABLES,
            markdown="# Cached",
        )
        mock_cache_manager.get_processed = AsyncMock(return_value=cached_content)

        result = await processing_service.get_cached("hash123")

        assert result == cached_content

    @pytest.mark.asyncio
    async def test_get_cached_returns_none_on_miss(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Test get_cached returns None on cache miss."""
        mock_cache_manager.get_processed = AsyncMock(return_value=None)

        result = await processing_service.get_cached("hash123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_uses_default_options(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Test get_cached uses default options when not provided."""
        mock_cache_manager.get_processed = AsyncMock(return_value=None)

        await processing_service.get_cached("hash123", None)

        mock_cache_manager.get_processed.assert_called_once()
        call_args = mock_cache_manager.get_processed.call_args
        assert isinstance(call_args[0][1], ProcessingOptions)


class TestProcessingServiceInvalidate:
    """Tests for invalidate method."""

    @pytest.mark.asyncio
    async def test_invalidate_returns_count(
        self,
        processing_service: ProcessingService,
        mock_cache_manager: MagicMock,
    ) -> None:
        """Test invalidate returns count from cache."""
        mock_cache_manager.invalidate = AsyncMock(return_value=3)

        count = await processing_service.invalidate("test_id")

        assert count == 3

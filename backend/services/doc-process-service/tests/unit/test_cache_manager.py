"""Tests for doc_process_service.cache.manager module."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from doc_process_service.cache.keys import CacheKeyBuilder
from doc_process_service.cache.manager import CacheManager, compute_content_hash
from doc_process_service.models.domain import ProcessingOptions
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_returns_sha256_hex(self) -> None:
        """Test returns SHA-256 hex digest."""
        content = b"test content"
        result = compute_content_hash(content)

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected
        assert len(result) == 64

    def test_different_content_different_hash(self) -> None:
        """Test different content produces different hash."""
        hash1 = compute_content_hash(b"content 1")
        hash2 = compute_content_hash(b"content 2")

        assert hash1 != hash2

    def test_same_content_same_hash(self) -> None:
        """Test same content produces same hash."""
        content = b"identical content"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)

        assert hash1 == hash2

    def test_empty_content(self) -> None:
        """Test hashing empty content."""
        result = compute_content_hash(b"")

        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


@pytest.fixture
def mock_redis_cache() -> MagicMock:
    """Create mock RedisCache for testing."""
    cache = MagicMock()
    cache.get_bytes = AsyncMock(return_value=None)
    cache.set_bytes = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    cache.exists = AsyncMock(return_value=False)
    return cache


@pytest.fixture
def cache_manager(mock_redis_cache: MagicMock) -> CacheManager:
    """Create CacheManager with mock RedisCache."""
    return CacheManager(
        cache=mock_redis_cache,
        raw_ttl=3600,
        processed_ttl=3600,
    )


class TestCacheManager:
    """Tests for CacheManager class."""

    def test_init(self, mock_redis_cache: MagicMock) -> None:
        """Test CacheManager initialization."""
        manager = CacheManager(
            cache=mock_redis_cache,
            raw_ttl=3600,
            processed_ttl=7200,
        )

        assert manager._cache is mock_redis_cache
        assert manager._raw_ttl == 3600
        assert manager._processed_ttl == 7200
        assert isinstance(manager._keys, CacheKeyBuilder)

    def test_init_with_custom_keys(self, mock_redis_cache: MagicMock) -> None:
        """Test CacheManager with custom key builder."""
        custom_keys = CacheKeyBuilder(prefix="custom", separator="-")
        manager = CacheManager(
            cache=mock_redis_cache,
            raw_ttl=100,
            processed_ttl=200,
            keys=custom_keys,
        )

        assert manager._keys is custom_keys

    @pytest.mark.asyncio
    async def test_set_and_get_raw(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test storing and retrieving raw content."""
        content_id = "test_content_1"
        raw_bytes = b"PDF content here"
        checksum = compute_content_hash(raw_bytes)

        mock_redis_cache.get_bytes.return_value = raw_bytes

        await cache_manager.set_raw(content_id, raw_bytes, checksum)
        result = await cache_manager.get_raw(content_id)

        assert result == raw_bytes
        mock_redis_cache.set_bytes.assert_called()
        mock_redis_cache.set.assert_called()

    @pytest.mark.asyncio
    async def test_get_raw_not_found(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test getting raw content that doesn't exist."""
        mock_redis_cache.get_bytes.return_value = None
        result = await cache_manager.get_raw("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_raw_stores_checksum(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test set_raw also stores checksum."""
        content_id = "content_with_checksum"
        raw_bytes = b"test bytes"
        checksum = "abc123def456"

        mock_redis_cache.get.return_value = checksum

        await cache_manager.set_raw(content_id, raw_bytes, checksum)
        result = await cache_manager.get_checksum(content_id)

        assert result == checksum

    @pytest.mark.asyncio
    async def test_get_checksum_not_found(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test getting checksum that doesn't exist."""
        mock_redis_cache.get.return_value = None
        result = await cache_manager.get_checksum("missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_processed(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test storing and retrieving processed content."""
        content_hash = "hash_xyz"
        snapshot = ProcessedDocumentSnapshot(
            content_id="c1",
            content_hash=content_hash,
            level=ProcessingLevel.TABLES,
            markdown="# Title\n\nContent",
            table_count=2,
            image_count=0,
        )
        options = ProcessingOptions(extract_tables=True)

        serialized = cache_manager._serialize_snapshot(snapshot)
        mock_redis_cache.get_bytes.return_value = serialized

        await cache_manager.set_processed(content_hash, snapshot)
        result = await cache_manager.get_processed(content_hash, options)

        assert result is not None
        assert result.markdown == snapshot.markdown
        assert result.level == snapshot.level
        assert result.table_count == snapshot.table_count

    @pytest.mark.asyncio
    async def test_get_processed_not_found(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test getting processed content that doesn't exist."""
        mock_redis_cache.get_bytes.return_value = None
        options = ProcessingOptions()
        result = await cache_manager.get_processed("missing_hash", options)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_highest_level(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test get_highest_level returns highest cached level."""
        content_hash = "hash_multi"

        def exists_side_effect(key: str) -> bool:
            return "tables" in key.lower()

        mock_redis_cache.exists = AsyncMock(side_effect=exists_side_effect)

        highest = await cache_manager.get_highest_level(content_hash)

        assert highest == ProcessingLevel.TABLES

    @pytest.mark.asyncio
    async def test_get_highest_level_none(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test get_highest_level returns None when nothing cached."""
        mock_redis_cache.exists.return_value = False
        result = await cache_manager.get_highest_level("uncached_hash")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test invalidating cached content."""
        content_id = "to_invalidate"

        deleted = await cache_manager.invalidate(content_id)

        assert deleted == 2
        assert mock_redis_cache.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_handles_os_error(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test invalidate gracefully handles OSError on delete."""
        mock_redis_cache.delete = AsyncMock(side_effect=OSError("connection lost"))

        deleted = await cache_manager.invalidate("broken_id")

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_has_content_changed_same(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test has_content_changed returns False for same content."""
        content_id = "change_test"
        checksum = compute_content_hash(b"original content")

        mock_redis_cache.get.return_value = checksum

        result = await cache_manager.has_content_changed(content_id, checksum)

        assert result is False

    @pytest.mark.asyncio
    async def test_has_content_changed_different(
        self, cache_manager: CacheManager, mock_redis_cache: MagicMock
    ) -> None:
        """Test has_content_changed returns True for different content."""
        content_id = "change_test"
        original_checksum = compute_content_hash(b"original content")
        new_checksum = compute_content_hash(b"modified content")

        mock_redis_cache.get.return_value = original_checksum

        result = await cache_manager.has_content_changed(content_id, new_checksum)

        assert result is True

    @pytest.mark.asyncio
    async def test_has_content_changed_no_cached(
        self, cache_manager: CacheManager, mock_redis_cache: MagicMock
    ) -> None:
        """Test has_content_changed returns False when no cached checksum."""
        mock_redis_cache.get.return_value = None

        result = await cache_manager.has_content_changed("uncached", "any_checksum")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_raw_handles_error(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test set_raw returns False on error."""
        mock_redis_cache.set_bytes.side_effect = OSError("Connection error")

        result = await cache_manager.set_raw("id", b"data", "checksum")

        assert result is False

    @pytest.mark.asyncio
    async def test_set_processed_handles_error(self, cache_manager: CacheManager, mock_redis_cache: MagicMock) -> None:
        """Test set_processed returns False on error."""
        mock_redis_cache.set_bytes.side_effect = OSError("Connection error")

        snapshot = ProcessedDocumentSnapshot(
            content_id="c1",
            content_hash="hash",
            level=ProcessingLevel.BASIC,
            markdown="Content",
            table_count=0,
            image_count=0,
        )

        result = await cache_manager.set_processed("hash", snapshot)

        assert result is False


class TestCacheManagerSerialization:
    """Tests for CacheManager serialization methods."""

    @pytest.fixture
    def manager(self, mock_redis_cache: MagicMock) -> CacheManager:
        """Create CacheManager for serialization tests."""
        return CacheManager(cache=mock_redis_cache, raw_ttl=100, processed_ttl=200)

    def test_serialize_snapshot(self, manager: CacheManager) -> None:
        """Test _serialize_snapshot produces valid JSON bytes."""
        snapshot = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hash123",
            level=ProcessingLevel.TABLES,
            markdown="# Test",
            html="<h1>Test</h1>",
            table_count=1,
            image_count=2,
            serialized_document="serialized",
        )

        result = manager._serialize_snapshot(snapshot)

        assert isinstance(result, bytes)
        import json

        data = json.loads(result)
        assert data["contentId"] == "test_id"
        assert data["markdown"] == "# Test"
        assert data["tableCount"] == 1

    def test_deserialize_snapshot(self, manager: CacheManager) -> None:
        """Test _deserialize_snapshot reconstructs ProcessedDocumentSnapshot."""
        snapshot = ProcessedDocumentSnapshot(
            content_id="test_id",
            content_hash="hash456",
            level=ProcessingLevel.OCR,
            markdown="# OCR Content",
            table_count=0,
            image_count=3,
        )

        serialized = manager._serialize_snapshot(snapshot)
        result = manager._deserialize_snapshot(serialized)

        assert result is not None
        assert result.content_id == snapshot.content_id
        assert result.level == snapshot.level
        assert result.markdown == snapshot.markdown
        assert result.image_count == snapshot.image_count

    def test_deserialize_snapshot_invalid_json(self, manager: CacheManager) -> None:
        """Test _deserialize_snapshot returns None for invalid JSON."""
        result = manager._deserialize_snapshot(b"not valid json")

        assert result is None

    def test_deserialize_snapshot_missing_fields(self, manager: CacheManager) -> None:
        """Test _deserialize_snapshot returns None for invalid JSON."""
        # betterproto2 raises KeyError for unknown/missing fields, which should be caught
        result = manager._deserialize_snapshot(b'{"partial": "data"}')

        assert result is None

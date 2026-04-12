"""Tests for doc_process_service.cache.keys module."""

from doc_process_service.cache.keys import CacheKeyBuilder


class TestCacheKeyBuilder:
    """Tests for CacheKeyBuilder dataclass."""

    def test_default_prefix_and_separator(self) -> None:
        """Test default prefix and separator values."""
        builder = CacheKeyBuilder()

        assert builder.prefix == "doc"
        assert builder.separator == ":"

    def test_custom_prefix_and_separator(self) -> None:
        """Test custom prefix and separator."""
        builder = CacheKeyBuilder(prefix="myapp", separator="-")

        assert builder.prefix == "myapp"
        assert builder.separator == "-"

    def test_raw_key_format(self) -> None:
        """Test raw content key generation."""
        builder = CacheKeyBuilder()

        key = builder.raw_key("content_123")

        assert key == "doc:raw:content_123"

    def test_raw_key_custom_prefix(self) -> None:
        """Test raw key with custom prefix."""
        builder = CacheKeyBuilder(prefix="test")

        key = builder.raw_key("abc")

        assert key == "test:raw:abc"

    def test_processed_key_format(self) -> None:
        """Test processed content key generation."""
        builder = CacheKeyBuilder()

        key = builder.processed_key("hash_xyz", "tables")

        assert key == "doc:processed:hash_xyz:tables"

    def test_processed_key_different_levels(self) -> None:
        """Test processed key for different levels."""
        builder = CacheKeyBuilder()

        key1 = builder.processed_key("hash1", "basic")
        key2 = builder.processed_key("hash1", "tables")
        key3 = builder.processed_key("hash1", "ocr")
        key4 = builder.processed_key("hash1", "full")

        assert key1 == "doc:processed:hash1:basic"
        assert key2 == "doc:processed:hash1:tables"
        assert key3 == "doc:processed:hash1:ocr"
        assert key4 == "doc:processed:hash1:full"

    def test_checksum_key_format(self) -> None:
        """Test checksum key generation."""
        builder = CacheKeyBuilder()

        key = builder.checksum_key("content_id_456")

        assert key == "doc:checksum:content_id_456"

    def test_task_key_format(self) -> None:
        """Test task key generation."""
        builder = CacheKeyBuilder()

        key = builder.task_key("task_789")

        assert key == "doc:task:task_789"

    def test_custom_separator_in_keys(self) -> None:
        """Test keys use custom separator."""
        builder = CacheKeyBuilder(prefix="app", separator="|")

        assert builder.raw_key("c1") == "app|raw|c1"
        assert builder.processed_key("h1", "tables") == "app|processed|h1|tables"
        assert builder.checksum_key("c2") == "app|checksum|c2"
        assert builder.task_key("t1") == "app|task|t1"

    def test_builder_is_frozen_dataclass(self) -> None:
        """Test CacheKeyBuilder is a frozen dataclass."""
        import dataclasses

        assert dataclasses.is_dataclass(CacheKeyBuilder)
        params = getattr(CacheKeyBuilder, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_keys_are_deterministic(self) -> None:
        """Test same inputs produce same keys."""
        builder = CacheKeyBuilder()

        key1 = builder.processed_key("hash_abc", "tables")
        key2 = builder.processed_key("hash_abc", "tables")

        assert key1 == key2

    def test_different_content_ids_produce_different_keys(self) -> None:
        """Test different content IDs produce different keys."""
        builder = CacheKeyBuilder()

        key1 = builder.raw_key("content_1")
        key2 = builder.raw_key("content_2")

        assert key1 != key2

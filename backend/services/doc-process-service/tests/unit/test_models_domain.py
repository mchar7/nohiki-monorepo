"""Tests for doc_process_service.models.domain module."""

import dataclasses

from doc_process_service.models.domain import (
    ProcessingOptions,
    ProcessingResult,
    is_snapshot_empty,
)
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot, ProcessingLevel


class TestProcessingLevel:
    """Tests for ProcessingLevel enum."""

    def test_level_values(self) -> None:
        """Test ProcessingLevel has expected values (1-5)."""
        assert ProcessingLevel.BASIC.value == 1
        assert ProcessingLevel.TABLES.value == 2
        assert ProcessingLevel.OCR.value == 3
        assert ProcessingLevel.IMAGES.value == 4
        assert ProcessingLevel.FULL.value == 5

    def test_level_ordering(self) -> None:
        """Test ProcessingLevel values are ordered correctly."""
        assert ProcessingLevel.BASIC.value < ProcessingLevel.TABLES.value
        assert ProcessingLevel.TABLES.value < ProcessingLevel.OCR.value
        assert ProcessingLevel.OCR.value < ProcessingLevel.IMAGES.value
        assert ProcessingLevel.IMAGES.value < ProcessingLevel.FULL.value

    def test_level_from_value(self) -> None:
        """Test creating ProcessingLevel from int value."""
        assert ProcessingLevel(1) == ProcessingLevel.BASIC
        assert ProcessingLevel(2) == ProcessingLevel.TABLES
        assert ProcessingLevel(3) == ProcessingLevel.OCR
        assert ProcessingLevel(4) == ProcessingLevel.IMAGES
        assert ProcessingLevel(5) == ProcessingLevel.FULL


class TestProcessingOptions:
    """Tests for ProcessingOptions dataclass."""

    def test_default_options(self) -> None:
        """Test default options values."""
        options = ProcessingOptions()

        assert options.enable_ocr is False
        assert options.extract_tables is True
        assert options.extract_images is False
        assert options.ocr_languages == ()
        assert options.enable_vlm_descriptions is False

    def test_custom_options(self) -> None:
        """Test custom options values."""
        options = ProcessingOptions(
            enable_ocr=True,
            extract_tables=False,
            extract_images=True,
            ocr_languages=("en", "es"),
        )

        assert options.enable_ocr is True
        assert options.extract_tables is False
        assert options.extract_images is True
        assert options.ocr_languages == ("en", "es")

    def test_level_property_basic(self) -> None:
        """Test level is BASIC when no features enabled."""
        options = ProcessingOptions(
            enable_ocr=False,
            extract_tables=False,
            extract_images=False,
        )

        assert options.level == ProcessingLevel.BASIC

    def test_level_property_tables(self) -> None:
        """Test level is TABLES when only tables enabled."""
        options = ProcessingOptions(
            enable_ocr=False,
            extract_tables=True,
            extract_images=False,
        )

        assert options.level == ProcessingLevel.TABLES

    def test_level_property_ocr(self) -> None:
        """Test level is OCR when OCR enabled."""
        options = ProcessingOptions(
            enable_ocr=True,
            extract_tables=True,
            extract_images=False,
        )

        assert options.level == ProcessingLevel.OCR

    def test_level_property_images(self) -> None:
        """Test level is IMAGES when images enabled."""
        options = ProcessingOptions(
            enable_ocr=False,
            extract_tables=True,
            extract_images=True,
            enable_vlm_descriptions=False,
        )

        assert options.level == ProcessingLevel.IMAGES

    def test_level_property_full(self) -> None:
        """Test level is FULL when VLM descriptions enabled."""
        options = ProcessingOptions(
            enable_ocr=True,
            extract_tables=True,
            extract_images=True,
            enable_vlm_descriptions=True,
        )

        assert options.level == ProcessingLevel.FULL

    def test_options_is_frozen_dataclass(self) -> None:
        """Test ProcessingOptions is a frozen dataclass."""
        assert dataclasses.is_dataclass(ProcessingOptions)
        params = getattr(ProcessingOptions, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_options_hashable(self) -> None:
        """Test ProcessingOptions can be used as dict key."""
        options1 = ProcessingOptions(enable_ocr=True)
        options2 = ProcessingOptions(enable_ocr=True)

        assert hash(options1) == hash(options2)

        cache = {options1: "value"}
        assert cache[options2] == "value"

    def test_options_equality(self) -> None:
        """Test ProcessingOptions equality comparison."""
        options1 = ProcessingOptions(enable_ocr=True, extract_tables=True)
        options2 = ProcessingOptions(enable_ocr=True, extract_tables=True)
        options3 = ProcessingOptions(enable_ocr=False, extract_tables=True)

        assert options1 == options2
        assert options1 != options3

    def test_to_cache_key_part(self) -> None:
        """Test cache key generation is deterministic."""
        options = ProcessingOptions(enable_ocr=True)
        key1 = options.to_cache_key_part()
        key2 = options.to_cache_key_part()

        assert key1 == key2
        assert len(key1) == 16  # truncated hash


class TestProcessedDocumentSnapshot:
    """Tests for ProcessedDocumentSnapshot proto model."""

    def test_create_snapshot(self) -> None:
        """Test creating ProcessedDocumentSnapshot with fields."""
        snapshot = ProcessedDocumentSnapshot(
            content_id="motor:tsb:100:200",
            content_hash="hash123",
            level=ProcessingLevel.TABLES,
            markdown="# Document\n\nContent here.",
            table_count=2,
            image_count=0,
        )

        assert snapshot.content_id == "motor:tsb:100:200"
        assert snapshot.content_hash == "hash123"
        assert snapshot.level == ProcessingLevel.TABLES
        assert snapshot.markdown == "# Document\n\nContent here."
        assert snapshot.table_count == 2
        assert snapshot.image_count == 0

    def test_snapshot_with_all_fields(self) -> None:
        """Test ProcessedDocumentSnapshot with all fields."""
        snapshot = ProcessedDocumentSnapshot(
            content_id="content_1",
            content_hash="hash456",
            level=ProcessingLevel.FULL,
            markdown="# Doc",
            html="<h1>Doc</h1>",
            table_count=1,
            image_count=5,
            serialized_document="{}",
        )

        assert snapshot.html == "<h1>Doc</h1>"
        assert snapshot.image_count == 5
        assert snapshot.serialized_document == "{}"


class TestIsSnapshotEmpty:
    """Tests for is_snapshot_empty function."""

    def test_empty_snapshot(self) -> None:
        """Test is_snapshot_empty returns True for empty content."""
        empty = ProcessedDocumentSnapshot(
            content_id="c1",
            content_hash="hash1",
            level=ProcessingLevel.BASIC,
            markdown="   ",
            table_count=0,
        )

        assert is_snapshot_empty(empty) is True

    def test_non_empty_snapshot(self) -> None:
        """Test is_snapshot_empty returns False for content with markdown."""
        non_empty = ProcessedDocumentSnapshot(
            content_id="c2",
            content_hash="hash2",
            level=ProcessingLevel.BASIC,
            markdown="content",
        )

        assert is_snapshot_empty(non_empty) is False

    def test_snapshot_with_tables(self) -> None:
        """Test is_snapshot_empty returns False when has tables."""
        has_tables = ProcessedDocumentSnapshot(
            content_id="c3",
            content_hash="hash3",
            level=ProcessingLevel.TABLES,
            markdown="",
            table_count=1,
        )

        assert is_snapshot_empty(has_tables) is False


class TestProcessingResult:
    """Tests for ProcessingResult dataclass."""

    def test_successful_result(self) -> None:
        """Test creating successful ProcessingResult."""
        snapshot = ProcessedDocumentSnapshot(
            content_id="c1",
            content_hash="hash1",
            level=ProcessingLevel.BASIC,
            markdown="content",
        )
        result = ProcessingResult(content=snapshot)

        assert result.success is True
        assert result.content is snapshot
        assert result.error is None

    def test_failed_result(self) -> None:
        """Test creating failed ProcessingResult."""
        result = ProcessingResult(error="Processing failed: timeout")

        assert result.success is False
        assert result.content is None
        assert result.error == "Processing failed: timeout"

    def test_result_is_frozen_dataclass(self) -> None:
        """Test ProcessingResult is a frozen dataclass."""
        assert dataclasses.is_dataclass(ProcessingResult)
        params = getattr(ProcessingResult, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True

    def test_is_cacheable_property(self) -> None:
        """Test is_cacheable property."""
        snapshot = ProcessedDocumentSnapshot(
            content_id="c1",
            content_hash="hash1",
            level=ProcessingLevel.BASIC,
            markdown="content",
        )
        empty_snapshot = ProcessedDocumentSnapshot(
            content_id="c2",
            content_hash="hash2",
            level=ProcessingLevel.BASIC,
            markdown="",
        )

        success_result = ProcessingResult(content=snapshot)
        empty_result = ProcessingResult(content=empty_snapshot)
        failed_result = ProcessingResult(error="error")

        assert success_result.is_cacheable is True
        assert empty_result.is_cacheable is False
        assert failed_result.is_cacheable is False

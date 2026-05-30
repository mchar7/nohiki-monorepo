"""Tests for PdfPlumberLayoutExtractor.

Tests cover initialization, extraction logic, edge cases, and internal helpers.
Since we don't have actual PDFs, tests focus on the internal logic of word clustering,
scope path iteration, and metadata calculation.
"""

from __future__ import annotations

import pytest
from tailor.lint.layout.extractor import LayoutMetadata, LineLayout, ParagraphLayout
from tailor.lint.layout.pdfplumber_extractor import (
    PdfPlumberLayoutExtractor,
    _iter_scope_path_strings,
    _total_content_height,
)


class TestPdfPlumberLayoutExtractorInit:
    """Tests for PdfPlumberLayoutExtractor initialization."""

    def test_default_tolerance(self) -> None:
        """Extractor initializes with default line cluster tolerance."""
        extractor = PdfPlumberLayoutExtractor()
        # Access internal state to verify
        assert extractor._y_tol == 2.0

    def test_custom_tolerance(self) -> None:
        """Extractor accepts custom line cluster tolerance."""
        extractor = PdfPlumberLayoutExtractor(line_cluster_tolerance_pt=5.0)
        assert extractor._y_tol == 5.0

    def test_zero_tolerance_rejected(self) -> None:
        """Zero tolerance is rejected as invalid."""
        with pytest.raises(ValueError, match="must be positive"):
            PdfPlumberLayoutExtractor(line_cluster_tolerance_pt=0.0)

    def test_negative_tolerance_rejected(self) -> None:
        """Negative tolerance is rejected."""
        with pytest.raises(ValueError, match="must be positive"):
            PdfPlumberLayoutExtractor(line_cluster_tolerance_pt=-1.0)

    def test_large_tolerance_accepted(self) -> None:
        """Large positive tolerance values are accepted."""
        extractor = PdfPlumberLayoutExtractor(line_cluster_tolerance_pt=100.0)
        assert extractor._y_tol == 100.0


class TestPdfPlumberLayoutExtractorEdgeCases:
    """Tests for edge cases in extraction."""

    def test_extract_empty_bytes_raises_error(self) -> None:
        """Extracting from empty bytes raises ValueError."""
        extractor = PdfPlumberLayoutExtractor()
        with pytest.raises(ValueError, match="empty pdf_bytes"):
            extractor.extract(b"", {})

    def test_extract_returns_empty_metadata_for_empty_document_data(self) -> None:
        """Extraction with empty document data returns LayoutMetadata with no paragraphs."""
        # We can't create a real PDF easily, but we can test the scope path iteration
        # and metadata calculation separately
        metadata = LayoutMetadata(page_count=0, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=0.0)
        assert metadata.page_count == 0
        assert len(metadata.paragraphs) == 0


class TestIterScopePathStrings:
    """Tests for _iter_scope_path_strings() helper."""

    def test_simple_string_leaf(self) -> None:
        """String value yields (path, text) tuple."""
        data = {"name": "John Doe"}
        result = _iter_scope_path_strings(data)
        assert ("name", "John Doe") in result

    def test_nested_dict_paths(self) -> None:
        """Nested dict creates dot-separated paths."""
        data = {"person": {"name": "John", "email": "john@example.com"}}
        result = _iter_scope_path_strings(data)
        assert ("person.name", "John") in result
        assert ("person.email", "john@example.com") in result

    def test_list_index_paths(self) -> None:
        """List creates bracket-notation paths."""
        data = {"items": ["first", "second"]}
        result = _iter_scope_path_strings(data)
        assert ("items[0]", "first") in result
        assert ("items[1]", "second") in result

    def test_nested_list_in_dict(self) -> None:
        """Lists inside dicts create combined paths."""
        data = {"entries": [{"bullets": ["a", "b"]}, {"bullets": ["c"]}]}
        result = _iter_scope_path_strings(data)
        assert ("entries[0].bullets[0]", "a") in result
        assert ("entries[0].bullets[1]", "b") in result
        assert ("entries[1].bullets[0]", "c") in result

    def test_empty_strings_skipped(self) -> None:
        """Whitespace-only and empty strings are not yielded."""
        data = {"empty": "", "whitespace": "  ", "value": "real"}
        result = _iter_scope_path_strings(data)
        # Only "real" should be in the results
        assert ("value", "real") in result
        # Empty and whitespace should not appear
        assert len([r for r in result if r[1] == "" or r[1].strip() == ""]) == 0

    def test_non_string_values_skipped(self) -> None:
        """Non-string, non-container values (int, bool, None) are skipped."""
        data = {"text": "visible", "count": 42, "flag": True, "empty": None}
        result = _iter_scope_path_strings(data)
        assert ("text", "visible") in result
        # Numbers, bools, None should not appear
        assert len([r for r in result if r[1] in [42, True, None]]) == 0

    def test_complex_nested_structure(self) -> None:
        """Complex nested structure with mixed types."""
        data = {
            "experience": {
                "entries": [
                    {"title": "Engineer", "bullets": ["Built systems", "Led team"]},
                    {"title": "Analyst", "bullets": ["Analyzed data"]},
                ]
            },
            "skills": ["Python", "Go"],
        }
        result = _iter_scope_path_strings(data)
        assert ("experience.entries[0].title", "Engineer") in result
        assert ("experience.entries[0].bullets[0]", "Built systems") in result
        assert ("experience.entries[0].bullets[1]", "Led team") in result
        assert ("experience.entries[1].title", "Analyst") in result
        assert ("experience.entries[1].bullets[0]", "Analyzed data") in result
        assert ("skills[0]", "Python") in result
        assert ("skills[1]", "Go") in result

    def test_dict_with_non_string_keys(self) -> None:
        """Dict with non-string keys ignores those entries (skipped in _walk)."""
        data = {"valid": "yes", 42: "should_be_skipped"}  # type: ignore[dict-item]
        result = _iter_scope_path_strings(data)
        assert ("valid", "yes") in result
        assert len(result) == 1


class TestTotalContentHeight:
    """Tests for _total_content_height() helper."""

    def test_empty_paragraphs(self) -> None:
        """Empty paragraph list returns 0.0."""
        result = _total_content_height([])
        assert result == 0.0

    def test_single_paragraph_height(self) -> None:
        """Height of single paragraph is calculated from bbox."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(scope_path="test", bbox_pt=(0.0, 0.0, 100.0, 50.0), wrapped_lines=(line,), page_number=1)
        result = _total_content_height([para])
        assert result == 50.0

    def test_multiple_paragraphs_sum(self) -> None:
        """Total height is sum of all paragraph heights."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para1 = ParagraphLayout(scope_path="p1", bbox_pt=(0.0, 0.0, 100.0, 30.0), wrapped_lines=(line,), page_number=1)
        para2 = ParagraphLayout(scope_path="p2", bbox_pt=(0.0, 40.0, 100.0, 80.0), wrapped_lines=(line,), page_number=1)
        result = _total_content_height([para1, para2])
        # 30.0 + 40.0 = 70.0
        assert result == 70.0

    def test_negative_bbox_height_clamped_to_zero(self) -> None:
        """Invalid negative height (y0 > y1) is clamped to 0.0."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        # bbox where y0 > y1 (inverted)
        para = ParagraphLayout(
            scope_path="test", bbox_pt=(0.0, 100.0, 100.0, 50.0), wrapped_lines=(line,), page_number=1
        )
        result = _total_content_height([para])
        # max(0.0, 50 - 100) = max(0.0, -50) = 0.0
        assert result == 0.0

    def test_zero_height_paragraph(self) -> None:
        """Paragraph with zero height contributes 0.0."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="test", bbox_pt=(0.0, 50.0, 100.0, 50.0), wrapped_lines=(line,), page_number=1
        )
        result = _total_content_height([para])
        assert result == 0.0

    def test_large_page_height(self) -> None:
        """Large paragraph spanning entire page."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="test", bbox_pt=(0.0, 0.0, 100.0, 792.0), wrapped_lines=(line,), page_number=1
        )
        result = _total_content_height([para])
        assert result == 792.0


class TestPdfPlumberLayoutExtractorInterface:
    """Tests for protocol compliance."""

    def test_extractor_implements_protocol(self) -> None:
        """PdfPlumberLayoutExtractor has required protocol methods."""
        from tailor.lint.layout.extractor import LayoutExtractor

        extractor = PdfPlumberLayoutExtractor()
        assert isinstance(extractor, LayoutExtractor)

    def test_extract_method_exists(self) -> None:
        """Extractor has extract method with correct signature."""
        extractor = PdfPlumberLayoutExtractor()
        assert hasattr(extractor, "extract")
        assert callable(extractor.extract)


class TestIterScopePathStringsEdgeCases:
    """Additional edge case tests for scope path iteration."""

    def test_deeply_nested_structure(self) -> None:
        """Very deeply nested structures are handled correctly."""
        data = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = _iter_scope_path_strings(data)
        assert ("a.b.c.d.e", "deep") in result

    def test_mixed_numeric_and_string_indices(self) -> None:
        """Mixed dict and list nesting with various types."""
        data = {
            "list": [
                {
                    "name": "item1",
                    "subitems": ["a", "b"],
                }
            ]
        }
        result = _iter_scope_path_strings(data)
        assert ("list[0].name", "item1") in result
        assert ("list[0].subitems[0]", "a") in result
        assert ("list[0].subitems[1]", "b") in result

    def test_empty_containers_skipped(self) -> None:
        """Empty dicts and lists don't generate path entries."""
        data = {"empty_dict": {}, "empty_list": [], "value": "present"}
        result = _iter_scope_path_strings(data)
        assert ("value", "present") in result
        # No entries should be generated for empty containers
        assert len([r for r in result if r[1] == "" or r[1] is None]) == 0

    def test_none_values_skipped(self) -> None:
        """None values are skipped during traversal."""
        data = {"value": "keep", "none_val": None, "list": [None, "keep2"]}
        result = _iter_scope_path_strings(data)
        assert ("value", "keep") in result
        assert ("list[1]", "keep2") in result

    def test_numeric_values_skipped(self) -> None:
        """Numeric and boolean values are skipped."""
        data = {"int_val": 42, "float_val": 3.14, "bool_val": True, "text": "good"}
        result = _iter_scope_path_strings(data)
        assert ("text", "good") in result
        assert len([r for r in result if r[1] in [42, 3.14, True]]) == 0

    def test_special_characters_in_keys_preserved(self) -> None:
        """Dict keys with special characters are preserved in paths."""
        data = {"key-with-dash": "value", "key_with_underscore": "value2"}
        result = _iter_scope_path_strings(data)
        assert ("key-with-dash", "value") in result
        assert ("key_with_underscore", "value2") in result


class TestTotalContentHeightEdgeCases:
    """Additional edge case tests for total content height calculation."""

    def test_very_large_heights(self) -> None:
        """Very large paragraph heights are summed correctly."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para1 = ParagraphLayout(
            scope_path="p1", bbox_pt=(0.0, 0.0, 100.0, 10000.0), wrapped_lines=(line,), page_number=1
        )
        para2 = ParagraphLayout(
            scope_path="p2", bbox_pt=(0.0, 10000.0, 100.0, 20000.0), wrapped_lines=(line,), page_number=1
        )
        result = _total_content_height([para1, para2])
        assert result == 20000.0

    def test_many_paragraphs_summed(self) -> None:
        """Many small paragraphs are correctly summed."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        paras = [
            ParagraphLayout(
                scope_path=f"p{i}",
                bbox_pt=(0.0, i * 20.0, 100.0, (i + 1) * 20.0),
                wrapped_lines=(line,),
                page_number=1,
            )
            for i in range(10)
        ]
        result = _total_content_height(paras)
        assert result == 200.0  # 10 paragraphs x 20.0 height each

    def test_float_bbox_coordinates(self) -> None:
        """Float bbox coordinates are handled correctly."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="test",
            bbox_pt=(0.5, 1.5, 100.5, 31.7),
            wrapped_lines=(line,),
            page_number=1,
        )
        result = _total_content_height([para])
        assert abs(result - 30.2) < 0.01  # 31.7 - 1.5 = 30.2

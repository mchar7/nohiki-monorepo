"""Tests for layout data models (LineLayout, ParagraphLayout, LayoutMetadata).

Tests cover valid construction, frozen immutability, extra field rejection,
field constraints (bounds, tuple shapes), and serialization/deserialization.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.layout.extractor import LayoutMetadata, LineLayout, ParagraphLayout


class TestLineLayout:
    """Tests for the LineLayout frozen Pydantic model."""

    def test_valid_construction(self) -> None:
        """Valid LineLayout with all required fields constructs successfully."""
        line = LineLayout(
            text="Sample line",
            bbox_pt=(10.0, 20.0, 100.0, 30.0),
            word_count=2,
            substantive_word_count=1,
        )
        assert line.text == "Sample line"
        assert line.bbox_pt == (10.0, 20.0, 100.0, 30.0)
        assert line.word_count == 2
        assert line.substantive_word_count == 1

    def test_frozen_field_rejects_mutation(self) -> None:
        """Frozen field prevents direct assignment and raises ValidationError."""
        line = LineLayout(text="Original", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        frozen_field = "text"
        with pytest.raises(ValidationError):
            setattr(line, frozen_field, "Modified")

    def test_word_count_ge_zero(self) -> None:
        """word_count must be >= 0; negative values rejected."""
        with pytest.raises(ValidationError):
            LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=-1, substantive_word_count=0)

    def test_substantive_word_count_ge_zero(self) -> None:
        """substantive_word_count must be >= 0; negative values rejected."""
        with pytest.raises(ValidationError):
            LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=-1)

    def test_bbox_pt_four_floats(self) -> None:
        """bbox_pt must be a 4-tuple of floats; wrong tuple size rejected."""
        with pytest.raises(ValidationError):
            # Use model_validate to bypass static type checking while testing pydantic validation
            LineLayout.model_validate(
                {"text": "test", "bbox_pt": [0.0, 0.0, 100.0], "word_count": 1, "substantive_word_count": 0}
            )

    def test_extra_forbid_rejects_unknown_fields(self) -> None:
        """extra='forbid' rejects unknown fields in construction."""
        with pytest.raises(ValidationError):
            LineLayout.model_validate(
                {
                    "text": "test",
                    "bbox_pt": [0.0, 0.0, 100.0, 20.0],
                    "word_count": 1,
                    "substantive_word_count": 0,
                    "unknown_field": "value",
                }
            )

    def test_empty_text(self) -> None:
        """Empty text string is allowed (no validation constraint)."""
        line = LineLayout(text="", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=0, substantive_word_count=0)
        assert line.text == ""

    def test_zero_word_count(self) -> None:
        """Zero word count is valid (edges case: no words on line)."""
        line = LineLayout(text="", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=0, substantive_word_count=0)
        assert line.word_count == 0


class TestParagraphLayout:
    """Tests for the ParagraphLayout frozen Pydantic model."""

    def test_valid_construction_single_line(self) -> None:
        """ParagraphLayout with one wrapped line constructs successfully."""
        line = LineLayout(text="Sample", bbox_pt=(10.0, 20.0, 100.0, 30.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="paragraphs[0]",
            bbox_pt=(10.0, 20.0, 100.0, 30.0),
            wrapped_lines=(line,),
            page_number=1,
        )
        assert para.scope_path == "paragraphs[0]"
        assert len(para.wrapped_lines) == 1
        assert para.page_number == 1

    def test_valid_construction_multiple_lines(self) -> None:
        """ParagraphLayout with multiple wrapped lines constructs successfully."""
        lines = tuple(
            LineLayout(
                text=f"Line {i}",
                bbox_pt=(10.0, 20.0 + i * 10, 100.0, 30.0 + i * 10),
                word_count=2,
                substantive_word_count=1,
            )
            for i in range(3)
        )
        para = ParagraphLayout(
            scope_path="records.entries[0].items[1]",
            bbox_pt=(10.0, 20.0, 100.0, 60.0),
            wrapped_lines=lines,
            page_number=2,
        )
        assert len(para.wrapped_lines) == 3
        assert para.page_number == 2

    def test_frozen_rejects_mutation(self) -> None:
        """Frozen model prevents field assignment."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="test_path",
            bbox_pt=(0.0, 0.0, 100.0, 20.0),
            wrapped_lines=(line,),
            page_number=1,
        )
        frozen_field = "scope_path"
        with pytest.raises(ValidationError):
            setattr(para, frozen_field, "new_path")

    def test_page_number_ge_one(self) -> None:
        """page_number must be >= 1; zero/negative rejected."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        with pytest.raises(ValidationError):
            ParagraphLayout(
                scope_path="test",
                bbox_pt=(0.0, 0.0, 100.0, 20.0),
                wrapped_lines=(line,),
                page_number=0,
            )

    def test_page_number_negative_rejected(self) -> None:
        """Negative page_number is rejected."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        with pytest.raises(ValidationError):
            ParagraphLayout(
                scope_path="test",
                bbox_pt=(0.0, 0.0, 100.0, 20.0),
                wrapped_lines=(line,),
                page_number=-1,
            )

    def test_bbox_pt_tuple_shape(self) -> None:
        """bbox_pt must be 4-tuple; wrong shape rejected."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        with pytest.raises(ValidationError):
            ParagraphLayout.model_validate(
                {
                    "scope_path": "test",
                    "bbox_pt": [0.0, 0.0, 100.0],
                    "wrapped_lines": [line],
                    "page_number": 1,
                }
            )

    def test_extra_forbid_rejects_unknown_fields(self) -> None:
        """extra='forbid' rejects unknown fields."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        with pytest.raises(ValidationError):
            ParagraphLayout.model_validate(
                {
                    "scope_path": "test",
                    "bbox_pt": [0.0, 0.0, 100.0, 20.0],
                    "wrapped_lines": [line],
                    "page_number": 1,
                    "extra_field": "value",
                }
            )

    def test_empty_wrapped_lines(self) -> None:
        """Empty wrapped_lines tuple is allowed (edge case)."""
        para = ParagraphLayout(
            scope_path="test",
            bbox_pt=(0.0, 0.0, 100.0, 20.0),
            wrapped_lines=(),
            page_number=1,
        )
        assert len(para.wrapped_lines) == 0


class TestLayoutMetadata:
    """Tests for the LayoutMetadata frozen Pydantic model."""

    def test_valid_construction_empty_document(self) -> None:
        """LayoutMetadata for empty PDF (no paragraphs) constructs successfully."""
        layout = LayoutMetadata(
            page_count=0,
            page_size_pt=(612.0, 792.0),
            paragraphs=(),
            total_content_height_pt=0.0,
        )
        assert layout.page_count == 0
        assert layout.page_size_pt == (612.0, 792.0)
        assert len(layout.paragraphs) == 0
        assert layout.total_content_height_pt == 0.0

    def test_valid_construction_single_page(self) -> None:
        """LayoutMetadata with one paragraph on one page constructs successfully."""
        line = LineLayout(text="Content", bbox_pt=(10.0, 20.0, 100.0, 30.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="body[0]",
            bbox_pt=(10.0, 20.0, 100.0, 30.0),
            wrapped_lines=(line,),
            page_number=1,
        )
        layout = LayoutMetadata(
            page_count=1,
            page_size_pt=(612.0, 792.0),
            paragraphs=(para,),
            total_content_height_pt=10.0,
        )
        assert layout.page_count == 1
        assert len(layout.paragraphs) == 1
        assert layout.total_content_height_pt == 10.0

    def test_valid_construction_multi_page(self) -> None:
        """LayoutMetadata with multiple paragraphs spanning multiple pages."""
        paras = tuple(
            ParagraphLayout(
                scope_path=f"body[{i}]",
                bbox_pt=(10.0, 20.0 + i * 300, 100.0, 30.0 + i * 300),
                wrapped_lines=(
                    LineLayout(
                        text=f"Para {i}",
                        bbox_pt=(10.0, 20.0 + i * 300, 100.0, 30.0 + i * 300),
                        word_count=2,
                        substantive_word_count=2,
                    ),
                ),
                page_number=i + 1,
            )
            for i in range(3)
        )
        layout = LayoutMetadata(
            page_count=3,
            page_size_pt=(612.0, 792.0),
            paragraphs=paras,
            total_content_height_pt=900.0,
        )
        assert layout.page_count == 3
        assert len(layout.paragraphs) == 3

    def test_frozen_rejects_mutation(self) -> None:
        """Frozen model prevents field assignment."""
        layout = LayoutMetadata(
            page_count=1,
            page_size_pt=(612.0, 792.0),
            paragraphs=(),
            total_content_height_pt=0.0,
        )
        frozen_field = "page_count"
        with pytest.raises(ValidationError):
            setattr(layout, frozen_field, 2)

    def test_page_count_ge_zero(self) -> None:
        """page_count must be >= 0; negative rejected."""
        with pytest.raises(ValidationError):
            LayoutMetadata(
                page_count=-1,
                page_size_pt=(612.0, 792.0),
                paragraphs=(),
                total_content_height_pt=0.0,
            )

    def test_total_content_height_ge_zero(self) -> None:
        """total_content_height_pt must be >= 0.0; negative rejected."""
        with pytest.raises(ValidationError):
            LayoutMetadata(
                page_count=0,
                page_size_pt=(612.0, 792.0),
                paragraphs=(),
                total_content_height_pt=-1.0,
            )

    def test_page_size_pt_tuple_shape(self) -> None:
        """page_size_pt must be 2-tuple; wrong shape rejected."""
        with pytest.raises(ValidationError):
            LayoutMetadata.model_validate(
                {"page_count": 0, "page_size_pt": [612.0], "paragraphs": [], "total_content_height_pt": 0.0}
            )

    def test_extra_forbid_rejects_unknown_fields(self) -> None:
        """extra='forbid' rejects unknown fields."""
        with pytest.raises(ValidationError):
            LayoutMetadata.model_validate(
                {
                    "page_count": 0,
                    "page_size_pt": [612.0, 792.0],
                    "paragraphs": [],
                    "total_content_height_pt": 0.0,
                    "unknown_field": "value",
                }
            )

    def test_us_letter_page_size(self) -> None:
        """US Letter page size (612x792 points) is typical and valid."""
        layout = LayoutMetadata(
            page_count=1,
            page_size_pt=(612.0, 792.0),
            paragraphs=(),
            total_content_height_pt=0.0,
        )
        assert layout.page_size_pt == (612.0, 792.0)

    def test_zero_page_count_with_paragraphs(self) -> None:
        """Edge case: page_count=0 but has paragraphs (invalid but schema-valid)."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 20.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="test",
            bbox_pt=(0.0, 0.0, 100.0, 20.0),
            wrapped_lines=(line,),
            page_number=1,
        )
        layout = LayoutMetadata(
            page_count=0,
            page_size_pt=(612.0, 792.0),
            paragraphs=(para,),
            total_content_height_pt=20.0,
        )
        assert layout.page_count == 0
        assert len(layout.paragraphs) == 1

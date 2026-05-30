"""Tests for layout rule implementations (OrphanDetected, PageOverflow, MaxPagesExceeded).

Tests cover parameter validation, detection logic, edge cases, and issue generation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.layout.extractor import LayoutMetadata, LineLayout, ParagraphLayout
from tailor.lint.layout.rules import (
    MaxPagesExceededParams,
    MaxPagesExceededRule,
    OrphanDetectedParams,
    OrphanDetectedRule,
    PageOverflowParams,
    PageOverflowRule,
)
from tailor.lint.models import Severity


class TestOrphanDetectedParamsValidation:
    """Tests for OrphanDetectedParams validation."""

    def test_valid_params_defaults(self) -> None:
        """Default parameters construct successfully."""
        params = OrphanDetectedParams()
        assert params.width_fill_ratio == 0.15
        assert params.min_substantive_words == 3
        assert params.exclude_single_line is True

    def test_valid_params_custom(self) -> None:
        """Custom valid parameters construct successfully."""
        params = OrphanDetectedParams(width_fill_ratio=0.25, min_substantive_words=5, exclude_single_line=False)
        assert params.width_fill_ratio == 0.25
        assert params.min_substantive_words == 5
        assert params.exclude_single_line is False

    def test_width_fill_ratio_must_be_positive(self) -> None:
        """width_fill_ratio must be > 0.0; zero/negative rejected."""
        with pytest.raises(ValidationError):
            OrphanDetectedParams(width_fill_ratio=0.0)

    def test_width_fill_ratio_must_not_exceed_one(self) -> None:
        """width_fill_ratio must be <= 1.0; higher values rejected."""
        with pytest.raises(ValidationError):
            OrphanDetectedParams(width_fill_ratio=1.1)

    def test_min_substantive_words_must_be_positive(self) -> None:
        """min_substantive_words must be >= 1; zero rejected."""
        with pytest.raises(ValidationError):
            OrphanDetectedParams(min_substantive_words=0)

    def test_frozen_prevents_mutation(self) -> None:
        """Frozen params prevent field mutation."""
        params = OrphanDetectedParams()
        frozen_field = "width_fill_ratio"
        with pytest.raises(ValidationError):
            setattr(params, frozen_field, 0.5)


class TestOrphanDetectedRule:
    """Tests for OrphanDetectedRule."""

    def test_flags_orphaned_final_line_by_width(self) -> None:
        """Paragraph with final line filling < width_fill_ratio is flagged."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.3)
        # Paragraph bbox: 100 units wide, final line only 20 units wide → 20% fill
        line1 = LineLayout(
            text="This is a full line", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=5, substantive_word_count=4
        )
        line2 = LineLayout(text="Short", bbox_pt=(0.0, 10.0, 20.0, 20.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="body[0]", bbox_pt=(0.0, 0.0, 100.0, 20.0), wrapped_lines=(line1, line2), page_number=1
        )
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=20.0
        )
        issues = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=[], params=params, layout=layout)
        assert len(issues) == 1
        assert issues[0].value is not None
        assert "Short" in issues[0].value or "Orphan" in issues[0].message

    def test_flags_orphaned_final_line_by_substantive_words(self) -> None:
        """Final line with < min_substantive_words is flagged even if width ratio OK."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.15, min_substantive_words=3)
        line1 = LineLayout(text="First line", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=2, substantive_word_count=2)
        line2 = LineLayout(text="and or", bbox_pt=(0.0, 10.0, 100.0, 20.0), word_count=2, substantive_word_count=0)
        para = ParagraphLayout(
            scope_path="body[0]", bbox_pt=(0.0, 0.0, 100.0, 20.0), wrapped_lines=(line1, line2), page_number=1
        )
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=20.0
        )
        issues = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=[], params=params, layout=layout)
        assert len(issues) == 1

    def test_exclude_single_line_skips_single_line_paragraphs(self) -> None:
        """When exclude_single_line=True, single-line paragraphs are never flagged."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.5, exclude_single_line=True)
        line = LineLayout(text="Short", bbox_pt=(0.0, 0.0, 20.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="body[0]", bbox_pt=(0.0, 0.0, 20.0, 10.0), wrapped_lines=(line,), page_number=1
        )
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=10.0
        )
        issues = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=[], params=params, layout=layout)
        assert len(issues) == 0

    def test_exclude_single_line_false_flags_single_lines(self) -> None:
        """When exclude_single_line=False, single-line paragraphs can be flagged."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.5, exclude_single_line=False)
        line = LineLayout(text="Short", bbox_pt=(0.0, 0.0, 20.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="body[0]", bbox_pt=(0.0, 0.0, 100.0, 10.0), wrapped_lines=(line,), page_number=1
        )
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=10.0
        )
        issues = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=[], params=params, layout=layout)
        assert len(issues) == 1

    def test_clean_paragraph_no_issue(self) -> None:
        """Paragraph with good final line returns no issue."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.15, min_substantive_words=3)
        line1 = LineLayout(text="First", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        line2 = LineLayout(
            text="Second line is long", bbox_pt=(0.0, 10.0, 90.0, 20.0), word_count=4, substantive_word_count=4
        )
        para = ParagraphLayout(
            scope_path="body[0]", bbox_pt=(0.0, 0.0, 100.0, 20.0), wrapped_lines=(line1, line2), page_number=1
        )
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=20.0
        )
        issues = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=[], params=params, layout=layout)
        assert len(issues) == 0

    def test_empty_wrapped_lines_skipped(self) -> None:
        """Paragraph with no wrapped lines is skipped."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams()
        para = ParagraphLayout(scope_path="body[0]", bbox_pt=(0.0, 0.0, 100.0, 20.0), wrapped_lines=(), page_number=1)
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=0.0
        )
        issues = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=[], params=params, layout=layout)
        assert len(issues) == 0

    def test_resolved_scope_filtering(self) -> None:
        """Resolved scope paths filter which paragraphs are checked."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.5, exclude_single_line=False)
        # Two paragraphs: one should be checked (matched in resolved), one skipped
        line_short = LineLayout(text="x", bbox_pt=(0.0, 0.0, 10.0, 10.0), word_count=1, substantive_word_count=1)
        line_long = LineLayout(
            text="full line", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=2, substantive_word_count=2
        )
        para1 = ParagraphLayout(
            scope_path="body[0]",
            bbox_pt=(0.0, 0.0, 100.0, 20.0),
            wrapped_lines=(line_long, line_short),
            page_number=1,
        )
        para2 = ParagraphLayout(
            scope_path="body[1]",
            bbox_pt=(0.0, 20.0, 100.0, 40.0),
            wrapped_lines=(line_long, line_short),
            page_number=1,
        )
        layout = LayoutMetadata(
            page_count=1,
            page_size_pt=(612.0, 792.0),
            paragraphs=(para1, para2),
            total_content_height_pt=40.0,
        )
        # Only check body[0]
        resolved = [("body[0]", [])]
        issues = rule.check(
            rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params, layout=layout
        )
        # Should flag para1 but not para2 because para2 not in resolved
        assert len(issues) == 1
        assert issues[0].path == "body[0]"

    def test_issue_has_correct_fields(self) -> None:
        """Emitted issue has correct rule_id, severity, path, and value."""
        rule = OrphanDetectedRule()
        params = OrphanDetectedParams(width_fill_ratio=0.9)
        line1 = LineLayout(text="Full", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        line2 = LineLayout(text="Bad", bbox_pt=(0.0, 10.0, 10.0, 20.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="body[2]", bbox_pt=(0.0, 0.0, 100.0, 20.0), wrapped_lines=(line1, line2), page_number=1
        )
        layout = LayoutMetadata(
            page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=20.0
        )
        issues = rule.check(
            rule_id="layout.orphan.test", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 1
        assert issues[0].rule == "layout.orphan.test"
        assert issues[0].severity == Severity.ERROR
        assert issues[0].path == "body[2]"
        assert issues[0].value == "Bad"


class TestPageOverflowParamsValidation:
    """Tests for PageOverflowParams validation."""

    def test_valid_params_no_tolerance(self) -> None:
        """Valid params with no tolerance construct successfully."""
        params = PageOverflowParams(max_pages=2, tolerance_pt=0.0)
        assert params.max_pages == 2
        assert params.tolerance_pt == 0.0

    def test_valid_params_with_tolerance(self) -> None:
        """Valid params with tolerance construct successfully."""
        params = PageOverflowParams(max_pages=2, tolerance_pt=50.0)
        assert params.max_pages == 2
        assert params.tolerance_pt == 50.0

    def test_max_pages_must_be_positive(self) -> None:
        """max_pages must be >= 1; zero/negative rejected."""
        with pytest.raises(ValidationError):
            PageOverflowParams(max_pages=0)

    def test_tolerance_must_be_nonnegative(self) -> None:
        """tolerance_pt must be >= 0.0; negative rejected."""
        with pytest.raises(ValidationError):
            PageOverflowParams(max_pages=1, tolerance_pt=-1.0)


class TestPageOverflowRule:
    """Tests for PageOverflowRule."""

    def test_no_issue_within_budget(self) -> None:
        """No issue when page_count <= max_pages."""
        rule = PageOverflowRule()
        params = PageOverflowParams(max_pages=2, tolerance_pt=0.0)
        layout = LayoutMetadata(
            page_count=2,
            page_size_pt=(612.0, 792.0),
            paragraphs=(),
            total_content_height_pt=1584.0,  # 2 pages
        )
        issues = rule.check(
            rule_id="layout.overflow", severity=Severity.WARNING, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 0

    def test_no_issue_with_tolerance(self) -> None:
        """No issue when overshoot is within tolerance_pt."""
        rule = PageOverflowRule()
        params = PageOverflowParams(max_pages=1, tolerance_pt=100.0)
        # Page height is 792, so 792 + 100 = 892 is within tolerance
        layout = LayoutMetadata(page_count=2, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=850.0)
        issues = rule.check(
            rule_id="layout.overflow", severity=Severity.WARNING, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 0

    def test_issue_when_exceeding_budget(self) -> None:
        """Issue emitted when content height exceeds max budget beyond tolerance."""
        rule = PageOverflowRule()
        params = PageOverflowParams(max_pages=1, tolerance_pt=0.0)
        layout = LayoutMetadata(
            page_count=2,
            page_size_pt=(612.0, 792.0),
            paragraphs=(),
            total_content_height_pt=1500.0,  # Well beyond 792
        )
        issues = rule.check(
            rule_id="layout.overflow", severity=Severity.WARNING, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 1
        assert "overflow" in issues[0].message.lower()

    def test_issue_path_is_root(self) -> None:
        """Page overflow issue path is always '$' (document root)."""
        rule = PageOverflowRule()
        params = PageOverflowParams(max_pages=1, tolerance_pt=0.0)
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        issues = rule.check(
            rule_id="layout.overflow", severity=Severity.INFO, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 1
        assert issues[0].path == "$"

    def test_issue_has_correct_severity(self) -> None:
        """Emitted issue respects the provided severity."""
        rule = PageOverflowRule()
        params = PageOverflowParams(max_pages=1, tolerance_pt=0.0)
        layout = LayoutMetadata(
            page_count=2, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2000.0
        )
        issues = rule.check(
            rule_id="layout.overflow", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert issues[0].severity == Severity.ERROR


class TestMaxPagesExceededParamsValidation:
    """Tests for MaxPagesExceededParams validation."""

    def test_valid_params(self) -> None:
        """Valid params construct successfully."""
        params = MaxPagesExceededParams(max_pages=2)
        assert params.max_pages == 2

    def test_max_pages_must_be_positive(self) -> None:
        """max_pages must be >= 1; zero/negative rejected."""
        with pytest.raises(ValidationError):
            MaxPagesExceededParams(max_pages=0)


class TestMaxPagesExceededRule:
    """Tests for MaxPagesExceededRule."""

    def test_no_issue_within_ceiling(self) -> None:
        """No issue when page_count <= max_pages."""
        rule = MaxPagesExceededRule()
        params = MaxPagesExceededParams(max_pages=2)
        layout = LayoutMetadata(
            page_count=2, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=1584.0
        )
        issues = rule.check(
            rule_id="layout.max_pages", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 0

    def test_issue_when_exceeding_ceiling(self) -> None:
        """Issue emitted when page_count > max_pages (no tolerance)."""
        rule = MaxPagesExceededRule()
        params = MaxPagesExceededParams(max_pages=2)
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        issues = rule.check(
            rule_id="layout.max_pages", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 1
        assert "exceeds" in issues[0].message.lower()

    def test_issue_path_is_root(self) -> None:
        """Max pages exceeded issue path is always '$'."""
        rule = MaxPagesExceededRule()
        params = MaxPagesExceededParams(max_pages=1)
        layout = LayoutMetadata(
            page_count=5, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=5000.0
        )
        issues = rule.check(
            rule_id="layout.max_pages", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert len(issues) == 1
        assert issues[0].path == "$"

    def test_issue_value_shows_excess(self) -> None:
        """Issue value shows the excess pages as '+N pages'."""
        rule = MaxPagesExceededRule()
        params = MaxPagesExceededParams(max_pages=2)
        layout = LayoutMetadata(
            page_count=5, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=5000.0
        )
        issues = rule.check(
            rule_id="layout.max_pages", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert issues[0].value is not None
        assert "+3 pages" in issues[0].value or "+3" in issues[0].value

    def test_issue_has_correct_rule_id_and_severity(self) -> None:
        """Emitted issue preserves rule_id and severity from check call."""
        rule = MaxPagesExceededRule()
        params = MaxPagesExceededParams(max_pages=1)
        layout = LayoutMetadata(
            page_count=2, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2000.0
        )
        issues = rule.check(
            rule_id="layout.hard_ceiling.reference", severity=Severity.ERROR, resolved=[], params=params, layout=layout
        )
        assert issues[0].rule == "layout.hard_ceiling.reference"
        assert issues[0].severity == Severity.ERROR

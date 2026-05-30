"""Tests for run_layout_lint() dispatcher function.

Tests cover rule evaluation, gating (tags, disabled_rule_ids), parameter validation,
and multi-rule dispatch.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.layout.extractor import LayoutMetadata, LineLayout, ParagraphLayout
from tailor.lint.layout.rules import LAYOUT_RULE_REGISTRY, run_layout_lint
from tailor.lint.models import RuleConfig, Severity
from tailor.lint.runtime import LintRuntimeContext


class TestRunLayoutLintBasic:
    """Tests for basic run_layout_lint() dispatch."""

    def test_empty_rule_configs_returns_empty_issues(self) -> None:
        """Empty rule_configs list returns no issues."""
        layout = LayoutMetadata(page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=0.0)
        issues = run_layout_lint((), layout)
        assert issues == []

    def test_single_rule_returns_issues(self) -> None:
        """Single rule config is evaluated and issues returned."""
        line = LineLayout(text="test", bbox_pt=(0.0, 0.0, 100.0, 10.0), word_count=1, substantive_word_count=1)
        para = ParagraphLayout(
            scope_path="body[0]", bbox_pt=(0.0, 0.0, 100.0, 10.0), wrapped_lines=(line,), page_number=1
        )
        layout = LayoutMetadata(
            page_count=2, page_size_pt=(612.0, 792.0), paragraphs=(para,), total_content_height_pt=10.0
        )
        cfg = RuleConfig(
            rule_id="layout.max_pages",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 1},  # Will trigger because page_count=2 > 1
        )
        issues = run_layout_lint((cfg,), layout, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues) > 0

    def test_multiple_rules_concatenated_issues(self) -> None:
        """Multiple rule configs return concatenated issues in order."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg1 = RuleConfig(
            rule_id="layout.page_overflow",
            type="page_overflow",
            severity=Severity.WARNING,
            scope_paths=("$",),
            params={"max_pages": 2, "tolerance_pt": 0.0},
        )
        cfg2 = RuleConfig(
            rule_id="layout.max_pages",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        issues = run_layout_lint((cfg1, cfg2), layout, registry=LAYOUT_RULE_REGISTRY)
        # Both rules should emit an issue
        assert len(issues) == 2

    def test_unknown_rule_type_raises_keyerror(self) -> None:
        """Unknown rule type in RuleConfig raises KeyError on dispatch."""
        layout = LayoutMetadata(page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=0.0)
        cfg = RuleConfig(
            rule_id="layout.unknown",
            type="unknown_rule_type",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={},
        )
        with pytest.raises(KeyError, match="Unknown layout rule type"):
            run_layout_lint((cfg,), layout, registry=LAYOUT_RULE_REGISTRY)

    def test_invalid_params_raises_validation_error(self) -> None:
        """Invalid params that fail rule's PARAMS_MODEL validation raise error."""
        layout = LayoutMetadata(page_count=1, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=0.0)
        cfg = RuleConfig(
            rule_id="layout.invalid",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 0},  # Invalid: must be >= 1
        )
        with pytest.raises(ValidationError):
            run_layout_lint((cfg,), layout, registry=LAYOUT_RULE_REGISTRY)


class TestRunLayoutLintGating:
    """Tests for rule gating (requires_tags, excludes_tags, disabled_rule_ids)."""

    def test_requires_tags_fires_when_tags_active(self) -> None:
        """Rule with requires_tags fires only when all required tags are active."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg = RuleConfig(
            rule_id="layout.max_pages.strict",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
            requires_tags=("strict_mode",),
        )
        # Without runtime context, requires_tags is not checked
        issues_no_runtime = run_layout_lint((cfg,), layout, runtime=None, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_no_runtime) == 0

        # With runtime but tag not active, rule should not fire
        runtime = LintRuntimeContext(active_tags=frozenset())
        issues_no_tag = run_layout_lint((cfg,), layout, runtime=runtime, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_no_tag) == 0

        # With runtime and tag active, rule should fire
        runtime_with_tag = LintRuntimeContext(active_tags=frozenset(["strict_mode"]))
        issues_with_tag = run_layout_lint((cfg,), layout, runtime=runtime_with_tag, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_with_tag) > 0

    def test_excludes_tags_skips_when_tags_active(self) -> None:
        """Rule with excludes_tags does not fire when any excluded tag is active."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg = RuleConfig(
            rule_id="layout.max_pages",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
            excludes_tags=("relaxed_mode",),
        )
        # With runtime and excluded tag active, rule should not fire
        runtime = LintRuntimeContext(active_tags=frozenset(["relaxed_mode"]))
        issues = run_layout_lint((cfg,), layout, runtime=runtime, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues) == 0

        # With runtime and excluded tag not active, rule should fire
        runtime_no_tag = LintRuntimeContext(active_tags=frozenset())
        issues_fire = run_layout_lint((cfg,), layout, runtime=runtime_no_tag, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_fire) > 0

    def test_disabled_rule_ids_skips_rule(self) -> None:
        """Rule listed in runtime.disabled_rule_ids is skipped."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg = RuleConfig(
            rule_id="layout.max_pages.test",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        # With rule not disabled, it fires
        runtime_enabled = LintRuntimeContext(disabled_rule_ids=frozenset())
        issues_enabled = run_layout_lint((cfg,), layout, runtime=runtime_enabled, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_enabled) > 0

        # With rule disabled, it doesn't fire
        runtime_disabled = LintRuntimeContext(disabled_rule_ids=frozenset(["layout.max_pages.test"]))
        issues_disabled = run_layout_lint((cfg,), layout, runtime=runtime_disabled, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_disabled) == 0

    def test_multiple_tags_all_required(self) -> None:
        """Multiple requires_tags all must be present for rule to fire."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg = RuleConfig(
            rule_id="layout.multi_tag",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
            requires_tags=("tag_a", "tag_b"),
        )
        # Only one tag present
        runtime_partial = LintRuntimeContext(active_tags=frozenset(["tag_a"]))
        issues_partial = run_layout_lint((cfg,), layout, runtime=runtime_partial, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_partial) == 0

        # Both tags present
        runtime_both = LintRuntimeContext(active_tags=frozenset(["tag_a", "tag_b"]))
        issues_both = run_layout_lint((cfg,), layout, runtime=runtime_both, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_both) > 0

    def test_multiple_excludes_tags_any_present_skips(self) -> None:
        """Any of excludes_tags being present skips the rule."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg = RuleConfig(
            rule_id="layout.exclude_multi",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
            excludes_tags=("exempt_a", "exempt_b"),
        )
        # One exclude tag present
        runtime_one = LintRuntimeContext(active_tags=frozenset(["exempt_a"]))
        issues_one = run_layout_lint((cfg,), layout, runtime=runtime_one, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_one) == 0

        # No exclude tags present
        runtime_none = LintRuntimeContext(active_tags=frozenset())
        issues_none = run_layout_lint((cfg,), layout, runtime=runtime_none, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues_none) > 0


class TestRunLayoutLintIssueFields:
    """Tests that run_layout_lint() preserves rule_id and severity in issues."""

    def test_issue_preserves_rule_id(self) -> None:
        """Issues returned have the rule_id from RuleConfig."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg = RuleConfig(
            rule_id="layout.my_custom_rule_id",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        issues = run_layout_lint((cfg,), layout, registry=LAYOUT_RULE_REGISTRY)
        assert len(issues) > 0
        assert issues[0].rule == "layout.my_custom_rule_id"

    def test_issue_preserves_severity(self) -> None:
        """Issues returned have the severity from RuleConfig."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg_error = RuleConfig(
            rule_id="layout.error_rule",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        cfg_warning = RuleConfig(
            rule_id="layout.warning_rule",
            type="max_pages_exceeded",
            severity=Severity.WARNING,
            scope_paths=("$",),
            params={"max_pages": 2},
        )
        issues_error = run_layout_lint((cfg_error,), layout, registry=LAYOUT_RULE_REGISTRY)
        assert issues_error[0].severity == Severity.ERROR

        issues_warning = run_layout_lint((cfg_warning,), layout, registry=LAYOUT_RULE_REGISTRY)
        assert issues_warning[0].severity == Severity.WARNING

    def test_issues_returned_in_config_order(self) -> None:
        """Issues are returned in the order of rule_configs."""
        layout = LayoutMetadata(
            page_count=3, page_size_pt=(612.0, 792.0), paragraphs=(), total_content_height_pt=2500.0
        )
        cfg1 = RuleConfig(
            rule_id="layout.first",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 1},
        )
        cfg2 = RuleConfig(
            rule_id="layout.second",
            type="max_pages_exceeded",
            severity=Severity.ERROR,
            scope_paths=("$",),
            params={"max_pages": 1},
        )
        issues = run_layout_lint((cfg1, cfg2), layout, registry=LAYOUT_RULE_REGISTRY)
        # Both should fire with max_pages=1 but page_count=3
        assert len(issues) == 2
        assert issues[0].rule == "layout.first"
        assert issues[1].rule == "layout.second"

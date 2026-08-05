"""Tests for the lint engine -- flat schema API."""

from __future__ import annotations

import pytest
from tailor.exceptions import LintConfigError
from tailor.lint import (
    META_KEY,
    LintConfig,
    LintEngine,
    LintRuntimeContext,
    RuleConfig,
    Severity,
)


class TestLintEngine:
    """Tests for LintEngine with flat schema config."""

    def test_single_rule_on_empty_data_returns_empty(self) -> None:
        """A rule whose scope resolves to an empty list emits no issues."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.min_items",
                    type="min_items",
                    severity=Severity.INFO,
                    scope_paths=("items",),
                    params={"value": 0},
                ),
            )
        )
        result = engine.evaluate({"items": []}, config)
        assert result.issues == ()

    def test_min_items_rule_flags_empty(self) -> None:
        """min_items rule fires when resolved path has fewer items than min."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.min_items",
                    type="min_items",
                    severity=Severity.ERROR,
                    scope_paths=("items",),
                    params={"value": 1},
                ),
            )
        )
        result = engine.evaluate({"items": []}, config)
        assert len(result.issues) == 1
        assert result.issues[0].rule == "test.min_items"

    def test_banned_patterns_rule_fires(self) -> None:
        """banned_patterns rule fires when a banned pattern matches."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.banned_patterns",
                    type="banned_patterns",
                    severity=Severity.WARNING,
                    scope_paths=("items",),
                    params={"patterns": [{"pattern": "bad word"}]},
                ),
            )
        )
        result = engine.evaluate({"items": ["this has a bad word in it"]}, config)
        assert any(issue.rule == "test.banned_patterns" for issue in result.issues)

    def test_min_total_words_rule_fires(self) -> None:
        """min_total_words rule fires when total word count is below minimum."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.min_total_words",
                    type="min_total_words",
                    severity=Severity.WARNING,
                    scope_paths=("items",),
                    params={"value": 100},
                ),
            )
        )
        result = engine.evaluate({"items": ["short text"]}, config)
        assert any(issue.rule == "test.min_total_words" for issue in result.issues)

    def test_required_sections_rule_fires(self) -> None:
        """required_sections rule fires when required section is missing."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.required_sections",
                    type="required_sections",
                    severity=Severity.ERROR,
                    scope_paths=("$",),
                    params={"value": ["skills"]},
                ),
            )
        )
        result = engine.evaluate({}, config)
        assert any(issue.rule == "test.required_sections" for issue in result.issues)

    def test_combined_rules_all_run(self) -> None:
        """Multiple rules all produce their respective issues."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.min_items",
                    type="min_items",
                    severity=Severity.ERROR,
                    scope_paths=("items",),
                    params={"value": 5},
                ),
                RuleConfig(
                    rule_id="test.required_sections",
                    type="required_sections",
                    severity=Severity.ERROR,
                    scope_paths=("$",),
                    params={"value": ["missing"]},
                ),
            )
        )
        result = engine.evaluate({"items": []}, config)
        rules_fired = {issue.rule for issue in result.issues}
        assert "test.min_items" in rules_fired
        assert "test.required_sections" in rules_fired

    def test_returns_tuple_of_lint_issues(self) -> None:
        """LintEngine.evaluate returns a tuple of LintIssue instances."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.min_items",
                    type="min_items",
                    severity=Severity.INFO,
                    scope_paths=("items",),
                    params={"value": 0},
                ),
            )
        )
        result = engine.evaluate({"items": []}, config)
        assert isinstance(result.issues, tuple)


class TestScopeExcludes:
    """The engine must honour ``scope_excludes`` when evaluating rules."""

    def test_excluded_path_does_not_fire(self) -> None:
        """A path listed in ``scope_excludes`` must be removed from the resolved set.

        ``scope_paths=["records[*].items"]`` normally resolves against every
        index. Listing ``records[0].items`` in ``scope_excludes`` removes just
        the first index; the rule must still fire on the second.
        """
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.min_items_excluded",
                    type="min_items",
                    severity=Severity.ERROR,
                    scope_paths=("records[*].items",),
                    scope_excludes=("records[0].items",),
                    params={"value": 5},
                ),
            )
        )
        data: dict[str, object] = {
            "records": [
                {"items": ["a", "b"]},  # would fail min_items=5 but is excluded
                {"items": ["c"]},  # fails min_items=5 and is NOT excluded
            ]
        }
        result = engine.evaluate(data, config)
        paths = {issue.path for issue in result.issues}
        # Only the non-excluded record should produce an issue.
        assert paths == {"$.records[1].items"}


class TestParamsValidation:
    """``PARAMS_MODEL`` errors must surface as ``LintConfigError`` with rule_id context."""

    def test_invalid_params_raises_lint_config_error(self) -> None:
        """Supplying params that fail ``PARAMS_MODEL`` validation raises with rule_id."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.bad_params",
                    type="min_items",
                    severity=Severity.INFO,
                    scope_paths=("items",),
                    # min_items requires ``value: int``; supplying a string
                    # triggers PARAMS_MODEL validation failure.
                    params={"value": "not an int"},
                ),
            )
        )
        with pytest.raises(LintConfigError, match=r"test\.bad_params"):
            engine.evaluate({"items": []}, config)

    def test_missing_variable_for_substitutable_param_raises(self) -> None:
        """A required ``{{ var }}`` in a substitutable param raises on evaluate."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.missing_var",
                    type="mention_count",
                    severity=Severity.WARNING,
                    scope_paths=("text",),
                    params={"target": "{{ missing_var }}", "min": 1},
                ),
            )
        )
        with pytest.raises(LintConfigError, match="missing_var"):
            engine.evaluate({"text": "hello"}, config, LintRuntimeContext())


class TestKwargForwarding:
    """Cross-path rules consume ``data`` and ``runtime`` kwargs from the engine."""

    def test_cross_path_rule_receives_data_kwarg(self) -> None:
        """``repeated_literal_across_paths`` must receive ``data`` so it can collect strings.

        If the engine failed to forward ``data``, the rule would raise
        ``RuntimeError("requires data and runtime kwargs from the engine")``.
        """
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.cross_path",
                    type="repeated_literal_across_paths",
                    severity=Severity.INFO,
                    scope_paths=("$",),
                    params={
                        "source_paths": ["section_a"],
                        "target_paths": ["section_b"],
                        "literal_type": "number",
                        "min_repeat_chars": 1,
                    },
                ),
            )
        )
        # Same literal '42' appears in both sources and targets.
        data: dict[str, object] = {"section_a": "first 42 here", "section_b": "also 42 here"}
        result = engine.evaluate(data, config)
        # Non-empty issues is sufficient proof that data was forwarded.
        assert any(issue.rule == "test.cross_path" for issue in result.issues)

    def test_sibling_resolved_uses_runtime(self) -> None:
        """``sibling.<name>.<path>`` resolution requires the engine to forward ``runtime``."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.sibling_access",
                    type="min_items",
                    severity=Severity.INFO,
                    scope_paths=("sibling.companion.items",),
                    params={"value": 5},
                ),
            )
        )
        runtime = LintRuntimeContext(sibling_documents={"companion": {"items": []}})
        result = engine.evaluate({}, config, runtime)
        # Sibling path resolved and min_items fired on the empty list.
        assert any(issue.rule == "test.sibling_access" for issue in result.issues)


class TestMetaKeyGuard:
    """Meta block is stripped from document data before evaluate() is called."""

    def test_evaluate_rejects_unstripped_meta(self) -> None:
        """Data still carrying ``_tailor_meta`` must raise ``LintConfigError``."""
        engine = LintEngine()
        config = LintConfig(
            rules=(
                RuleConfig(
                    rule_id="test.noop",
                    type="min_items",
                    severity=Severity.INFO,
                    scope_paths=("items",),
                    params={"value": 0},
                ),
            )
        )
        with pytest.raises(LintConfigError, match=META_KEY):
            engine.evaluate({META_KEY: {"lint_tags": []}, "items": []}, config)

"""Tests for tailor.lint models -- flat schema API.

Covers Severity enum, LintIssue, RuleConfig, and top-level LintConfig.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint import (
    BannedPattern,
    LayoutConfig,
    LintConfig,
    LintIssue,
    RuleConfig,
    Severity,
)


class TestSeverity:
    """Tests for the Severity StrEnum."""

    def test_exactly_three_members(self) -> None:
        """Severity must have exactly 3 members."""
        assert len(list(Severity)) == 3

    def test_error_member_exists(self) -> None:
        """Severity.ERROR must exist with value 'error'."""
        assert Severity.ERROR == "error"

    def test_warning_member_exists(self) -> None:
        """Severity.WARNING must exist with value 'warning'."""
        assert Severity.WARNING == "warning"

    def test_info_member_exists(self) -> None:
        """Severity.INFO must exist with value 'info'."""
        assert Severity.INFO == "info"

    def test_string_to_enum_coercion(self) -> None:
        """Severity must coerce from string values."""
        assert Severity("error") == Severity.ERROR
        assert Severity("warning") == Severity.WARNING
        assert Severity("info") == Severity.INFO

    def test_invalid_value_raises(self) -> None:
        """Severity must reject unknown string values."""
        with pytest.raises(ValueError, match="critical"):
            Severity("critical")


class TestLintIssue:
    """Tests for LintIssue."""

    def test_construction_with_required_fields(self) -> None:
        """LintIssue must construct with rule, severity, path, message."""
        issue = LintIssue(
            rule="test.rule",
            severity=Severity.ERROR,
            path="test.path",
            message="Test message",
        )
        assert issue.rule == "test.rule"
        assert issue.severity == Severity.ERROR
        assert issue.path == "test.path"
        assert issue.message == "Test message"

    def test_value_defaults_to_none(self) -> None:
        """LintIssue.value must default to None."""
        issue = LintIssue(
            rule="test.rule",
            severity=Severity.WARNING,
            path="test.path",
            message="Test",
        )
        assert issue.value is None

    def test_value_can_be_set(self) -> None:
        """LintIssue.value must accept a string."""
        issue = LintIssue(
            rule="test.rule",
            severity=Severity.INFO,
            path="test.path",
            message="Test",
            value="test_value",
        )
        assert issue.value == "test_value"

    def test_is_frozen_immutable(self) -> None:
        """LintIssue must be frozen."""
        issue = LintIssue(
            rule="test.rule",
            severity=Severity.ERROR,
            path="test.path",
            message="Test",
        )
        # Dynamic attribute name prevents the type checker from flagging the
        # intentional read-only write while still exercising pydantic's
        # ``FrozenInstance`` guard at runtime.
        frozen_field = "rule"
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            setattr(issue, frozen_field, "new.rule")

    def test_severity_coerced_from_string(self) -> None:
        """LintIssue must accept severity as string."""
        issue = LintIssue.model_validate(
            {
                "rule": "test.rule",
                "severity": "error",
                "path": "test.path",
                "message": "Test",
            }
        )
        assert issue.severity == Severity.ERROR


class TestBannedPattern:
    """Tests for BannedPattern."""

    def test_construction(self) -> None:
        """BannedPattern must accept pattern."""
        bp = BannedPattern(pattern="test pattern")
        assert bp.pattern == "test pattern"

    def test_defaults(self) -> None:
        """BannedPattern message defaults to empty."""
        bp = BannedPattern(pattern="test")
        assert bp.message == ""

    def test_unknown_key_rejected(self) -> None:
        """BannedPattern must reject unknown keys."""
        with pytest.raises(ValidationError):
            BannedPattern.model_validate({"pattern": "x", "unknown": "y"})

    def test_valid_regex_accepted(self) -> None:
        """BannedPattern must accept valid regex."""
        bp = BannedPattern(pattern=r"\btest\b")
        assert bp.pattern == r"\btest\b"

    def test_invalid_regex_raises_validation_error(self) -> None:
        """BannedPattern must raise ValidationError for invalid regex."""
        with pytest.raises(ValidationError):
            BannedPattern(pattern="[invalid")


class TestRuleConfig:
    """Tests for RuleConfig."""

    def test_construction_with_required_fields(self) -> None:
        """RuleConfig requires rule_id, type, severity, scope_paths."""
        cfg = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
            params={"value": 3},
        )
        assert cfg.rule_id == "test.rule"
        assert cfg.type == "min_items"
        assert cfg.severity == Severity.WARNING
        assert cfg.scope_paths == ("items",)
        assert cfg.params == {"value": 3}

    def test_severity_is_required(self) -> None:
        """RuleConfig.severity has no default; YAML authors must be explicit."""
        # ``model_validate`` sidesteps positional/keyword signature checks so
        # the test targets runtime validation rather than a static-analysis error.
        with pytest.raises(ValidationError):
            RuleConfig.model_validate(
                {
                    "rule_id": "test.rule",
                    "type": "min_items",
                    "scope_paths": ("items",),
                }
            )

    def test_params_defaults_to_empty_dict(self) -> None:
        """RuleConfig.params defaults to empty dict."""
        cfg = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
        )
        assert cfg.params == {}

    def test_requires_tags_defaults_to_empty(self) -> None:
        """RuleConfig.requires_tags defaults to empty tuple."""
        cfg = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
        )
        assert cfg.requires_tags == ()

    def test_excludes_tags_defaults_to_empty(self) -> None:
        """RuleConfig.excludes_tags defaults to empty tuple."""
        cfg = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
        )
        assert cfg.excludes_tags == ()

    def test_scope_excludes_defaults_to_empty(self) -> None:
        """RuleConfig.scope_excludes defaults to empty tuple."""
        cfg = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
        )
        assert cfg.scope_excludes == ()

    def test_unknown_key_rejected(self) -> None:
        """RuleConfig must reject unknown keys."""
        with pytest.raises(ValidationError):
            RuleConfig.model_validate(
                {
                    "rule_id": "test",
                    "type": "min_items",
                    "scope_paths": ("items",),
                    "unknown_field": "x",
                }
            )

    def test_is_frozen(self) -> None:
        """RuleConfig must be frozen."""
        cfg = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
        )
        frozen_field = "rule_id"
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            setattr(cfg, frozen_field, "new.rule")


class TestLintConfig:
    """Tests for LintConfig top-level config."""

    def test_rejects_empty_rules(self) -> None:
        """The rules list is required and must not be empty."""
        with pytest.raises(ValidationError, match="rules must be non-empty"):
            LintConfig(rules=())

    def test_accepts_rules(self) -> None:
        """LintConfig must accept RuleConfig instances."""
        rule = RuleConfig(
            rule_id="test.rule",
            type="min_items",
            severity=Severity.WARNING,
            scope_paths=("items",),
            params={"value": 3},
        )
        cfg = LintConfig(rules=(rule,))
        assert len(cfg.rules) == 1
        assert cfg.rules[0].rule_id == "test.rule"

    def test_accepts_layout(self) -> None:
        """LintConfig must accept LayoutConfig."""
        rule = RuleConfig(
            rule_id="placeholder.rule",
            type="min_items",
            severity=Severity.INFO,
            scope_paths=("items",),
            params={"value": 1},
        )
        layout = LayoutConfig(rules=())
        cfg = LintConfig(rules=(rule,), layout=layout)
        assert cfg.layout is not None

    def test_unknown_key_rejected(self) -> None:
        """LintConfig must reject unknown keys."""
        rule = RuleConfig(
            rule_id="placeholder.rule",
            type="min_items",
            severity=Severity.INFO,
            scope_paths=("items",),
            params={"value": 1},
        )
        with pytest.raises(ValidationError):
            LintConfig.model_validate(
                {
                    "rules": (rule.model_dump(),),
                    "unknown": "x",
                }
            )

    def test_is_frozen(self) -> None:
        """LintConfig must be frozen."""
        rule = RuleConfig(
            rule_id="placeholder.rule",
            type="min_items",
            severity=Severity.INFO,
            scope_paths=("items",),
            params={"value": 1},
        )
        cfg = LintConfig(rules=(rule,))
        frozen_field = "rules"
        with pytest.raises((TypeError, AttributeError, ValidationError)):
            setattr(cfg, frozen_field, ())


class TestLayoutConfig:
    """Tests for LayoutConfig."""

    def test_empty_construction(self) -> None:
        """LayoutConfig must construct with rules tuple."""
        cfg = LayoutConfig(rules=())
        assert cfg.rules == ()

    def test_unknown_key_rejected(self) -> None:
        """LayoutConfig must reject unknown keys."""
        with pytest.raises(ValidationError):
            LayoutConfig.model_validate({"rules": (), "unknown": "x"})


class TestExtraForbid:
    """Tests that all config models reject unknown keys."""

    _PLACEHOLDER_RULE_DICT = {
        "rule_id": "placeholder.rule",
        "type": "min_items",
        "severity": "info",
        "scope_paths": ("items",),
        "params": {"value": 0},
    }

    @pytest.mark.parametrize(
        ("model_class", "valid_data"),
        [
            (LintConfig, {"rules": (_PLACEHOLDER_RULE_DICT,)}),
            (LayoutConfig, {"rules": ()}),
            (RuleConfig, {"rule_id": "x", "type": "min_items", "scope_paths": ("items",)}),
            (BannedPattern, {"pattern": "x"}),
        ],
    )
    def test_unknown_key_raises_validation_error(
        self,
        model_class: type,
        valid_data: dict,
    ) -> None:
        """Every config model must reject unknown keys via extra='forbid'."""
        with pytest.raises(ValidationError):
            model_class(**valid_data, injected_unknown_key="should_fail")


class TestFlatSchemaValidation:
    """Tests that flat schema YAML parses correctly."""

    def test_flat_rules_list_parses(self) -> None:
        """Flat rules list must parse correctly."""
        data = {
            "rules": [
                {
                    "rule_id": "content.items.min_items",
                    "type": "min_items",
                    "severity": "error",
                    "scope_paths": ["records.entries[*].items"],
                    "params": {"value": 1},
                },
                {
                    "rule_id": "content.items.max_items",
                    "type": "max_items",
                    "severity": "warning",
                    "scope_paths": ["records.entries[*].items"],
                    "params": {"value": 6},
                },
            ]
        }
        config = LintConfig.model_validate(data)
        assert len(config.rules) == 2
        assert config.rules[0].type == "min_items"
        assert config.rules[1].type == "max_items"

    def test_rule_with_scope_excludes_parses(self) -> None:
        """Rule with scope_excludes must parse correctly."""
        data = {
            "rules": [
                {
                    "rule_id": "test.rule",
                    "type": "min_items",
                    "severity": "warning",
                    "scope_paths": ["items"],
                    "scope_excludes": ["items[0]"],
                    "params": {"value": 1},
                }
            ]
        }
        config = LintConfig.model_validate(data)
        assert config.rules[0].scope_excludes == ("items[0]",)

    def test_rule_with_tags_parses(self) -> None:
        """Rule with requires_tags and excludes_tags must parse."""
        data = {
            "rules": [
                {
                    "rule_id": "test.rule",
                    "type": "min_items",
                    "severity": "error",
                    "scope_paths": ["items"],
                    "requires_tags": ["strict"],
                    "excludes_tags": ["draft"],
                    "params": {"value": 1},
                }
            ]
        }
        config = LintConfig.model_validate(data)
        assert config.rules[0].requires_tags == ("strict",)
        assert config.rules[0].excludes_tags == ("draft",)

    def test_layout_rules_parses(self) -> None:
        """Layout rules must parse correctly alongside a non-empty content rules list."""
        placeholder_rule = {
            "rule_id": "placeholder.rule",
            "type": "min_items",
            "severity": "info",
            "scope_paths": ["items"],
            "params": {"value": 0},
        }
        data = {
            "rules": [placeholder_rule],
            "layout": {
                "rules": [
                    {
                        "rule_id": "layout.max_pages",
                        "type": "max_pages",
                        "severity": "error",
                        "scope_paths": ["$"],
                        "params": {"value": 1},
                    }
                ]
            },
        }
        config = LintConfig.model_validate(data)
        assert config.layout is not None
        assert len(config.layout.rules) == 1
        assert config.layout.rules[0].type == "max_pages"

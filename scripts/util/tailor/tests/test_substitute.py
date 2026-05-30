"""Tests for tailor.lint.substitute module.

Tests cover {{ var }} substitution for rule params.
"""

from __future__ import annotations

from typing import cast

import pytest
from tailor.exceptions import LintConfigError
from tailor.lint.substitute import substitute_params, substitute_string


class TestSubstituteString:
    """Tests for substitute_string()."""

    def test_single_placeholder_expansion(self) -> None:
        """substitute_string expands a single {{ var }}."""
        value = "Hello {{ name }}"
        variables = {"name": "Alice"}
        result = substitute_string(value, variables, context="test")
        assert result == "Hello Alice"

    def test_multiple_placeholders_in_same_string(self) -> None:
        """substitute_string expands multiple {{ var }} in same string."""
        value = "{{ first }} {{ last }}"
        variables = {"first": "John", "last": "Doe"}
        result = substitute_string(value, variables, context="test")
        assert result == "John Doe"

    def test_placeholder_with_optional_whitespace(self) -> None:
        """substitute_string handles whitespace in {{ var }}."""
        # No space
        assert substitute_string("{{foo}}", {"foo": "bar"}, context="test") == "bar"
        # Spaces
        assert substitute_string("{{ foo }}", {"foo": "bar"}, context="test") == "bar"
        # Extra spaces
        assert substitute_string("{{  foo  }}", {"foo": "bar"}, context="test") == "bar"

    def test_leaves_non_placeholder_text_alone(self) -> None:
        """substitute_string leaves non-placeholder text unchanged."""
        value = "Some {{ var }} with other text"
        variables = {"var": "VALUE"}
        result = substitute_string(value, variables, context="test")
        assert result == "Some VALUE with other text"

    def test_raises_when_variable_missing(self) -> None:
        """substitute_string raises LintConfigError for missing variable."""
        value = "Hello {{ missing }}"
        variables = {"other": "value"}
        with pytest.raises(LintConfigError, match="Unknown variable"):
            substitute_string(value, variables, context="test")

    def test_missing_variable_error_includes_context(self) -> None:
        """substitute_string error message includes context."""
        value = "{{ missing }}"
        variables = {}
        with pytest.raises(LintConfigError, match=r"rule_id=.*param="):
            substitute_string(value, variables, context="rule_id='foo' param='bar'")

    def test_returns_unchanged_when_no_placeholders(self) -> None:
        """substitute_string returns unchanged string when no placeholders."""
        value = "No placeholders here"
        variables = {"foo": "bar"}
        result = substitute_string(value, variables, context="test")
        assert result == "No placeholders here"

    def test_single_braces_not_substituted(self) -> None:
        """substitute_string leaves single braces unchanged (not double)."""
        value = "Single { braces } not substituted"
        variables = {"braces": "should not expand"}
        result = substitute_string(value, variables, context="test")
        assert result == "Single { braces } not substituted"

    def test_repeated_same_variable(self) -> None:
        """substitute_string handles same variable referenced multiple times."""
        value = "{{ x }} plus {{ x }}"
        variables = {"x": "5"}
        result = substitute_string(value, variables, context="test")
        assert result == "5 plus 5"


class TestSubstituteParams:
    """Tests for substitute_params()."""

    def test_returns_copy_when_substitutable_fields_empty(self) -> None:
        """substitute_params returns copy of params when substitutable_fields is empty."""
        params = cast(dict[str, object], {"foo": "{{ bar }}", "baz": "qux"})
        result = substitute_params(params, frozenset(), {"bar": "VALUE"}, rule_id="test.rule")
        assert result == params
        assert result is not params  # Should be a copy

    def test_substitutes_only_declared_fields(self) -> None:
        """substitute_params substitutes only fields in substitutable_fields."""
        params = cast(dict[str, object], {"target": "{{ var }}", "pattern": "{{ var }}"})
        variables = {"var": "VALUE"}
        result = substitute_params(params, frozenset(("target",)), variables, rule_id="test.rule")
        # Only 'target' is substituted
        assert result["target"] == "VALUE"
        # 'pattern' is copied as-is
        assert result["pattern"] == "{{ var }}"

    def test_leaves_non_substitutable_fields_alone(self) -> None:
        """substitute_params leaves non-substitutable fields unchanged."""
        params = cast(dict[str, object], {"substitutable": "{{ x }}", "other": "{{ x }}"})
        variables = {"x": "VALUE"}
        result = substitute_params(params, frozenset(("substitutable",)), variables, rule_id="test.rule")
        assert result["substitutable"] == "VALUE"
        assert result["other"] == "{{ x }}"

    def test_leaves_non_string_values_alone(self) -> None:
        """substitute_params leaves non-string values untouched for substitutable fields."""
        params = cast(dict[str, object], {"num": 42, "bool": True, "list": [1, 2, 3]})
        result = substitute_params(params, frozenset(("num", "bool", "list")), {}, rule_id="test.rule")
        assert result["num"] == 42
        assert result["bool"] is True
        assert result["list"] == [1, 2, 3]

    def test_raises_for_missing_variable_with_rule_id(self) -> None:
        """substitute_params raises LintConfigError for missing var with rule_id in message."""
        params = cast(dict[str, object], {"target": "{{ missing }}"})
        with pytest.raises(LintConfigError) as exc_info:
            substitute_params(params, frozenset(("target",)), {}, rule_id="my.rule.id")
        assert "my.rule.id" in str(exc_info.value)

    def test_only_substitutes_strings_with_placeholders(self) -> None:
        """substitute_params only processes string fields that contain placeholders."""
        params = cast(
            dict[str, object],
            {
                "text_with_placeholder": "prefix {{ x }} suffix",
                "text_without_placeholder": "plain text",
                "number": 42,
            },
        )
        variables = {"x": "EXPANDED"}
        result = substitute_params(
            params,
            frozenset(("text_with_placeholder", "text_without_placeholder", "number")),
            variables,
            rule_id="test.rule",
        )
        assert result["text_with_placeholder"] == "prefix EXPANDED suffix"
        assert result["text_without_placeholder"] == "plain text"
        assert result["number"] == 42

    def test_multiple_placeholders_in_same_field(self) -> None:
        """substitute_params handles multiple placeholders in one field."""
        params = cast(dict[str, object], {"template": "{{ a }}-{{ b }}-{{ c }}"})
        variables = {"a": "X", "b": "Y", "c": "Z"}
        result = substitute_params(params, frozenset(("template",)), variables, rule_id="test.rule")
        assert result["template"] == "X-Y-Z"

    def test_preserves_original_params(self) -> None:
        """substitute_params does not mutate original params dict."""
        params = cast(dict[str, object], {"field": "{{ x }}"})
        variables = {"x": "VALUE"}
        substitute_params(params, frozenset(("field",)), variables, rule_id="test.rule")
        assert params["field"] == "{{ x }}"

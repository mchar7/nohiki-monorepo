"""Tests for word budget rules -- flat schema API.

Covers MinTotalWordsRule and MaxTotalWordsRule with total word count
aggregation across configured scope paths.
"""

from __future__ import annotations

from tailor.lint.content.rules.word_budget_rules import (
    MaxTotalWordsParams,
    MaxTotalWordsRule,
    MinTotalWordsParams,
    MinTotalWordsRule,
)
from tailor.lint.models import Severity


class TestMinTotalWordsRule:
    """Tests for MinTotalWordsRule with flat schema params."""

    def test_flags_below_min(self) -> None:
        """Total below min must produce one issue."""
        rule = MinTotalWordsRule()
        params = MinTotalWordsParams(value=10)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]  # 5 words
        result = rule.check(rule_id="min_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1
        assert result[0].rule == "min_words"
        assert "5" in result[0].message  # actual count

    def test_passes_at_min(self) -> None:
        """Total equal to min must produce no issue."""
        rule = MinTotalWordsRule()
        params = MinTotalWordsParams(value=5)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]  # 5 words
        result = rule.check(rule_id="min_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_passes_above_min(self) -> None:
        """Total above min must produce no issue."""
        rule = MinTotalWordsRule()
        params = MinTotalWordsParams(value=3)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]  # 5 words
        result = rule.check(rule_id="min_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_skips_non_string_items(self) -> None:
        """Non-string items in resolved lists do not contribute to word count."""
        rule = MinTotalWordsRule()
        params = MinTotalWordsParams(value=4)
        resolved: list[tuple[str, list[object]]] = [("bullets", [42, None, {"key": "val"}, True, "three words here"])]
        result = rule.check(rule_id="min_words", severity=Severity.WARNING, resolved=resolved, params=params)
        # Only "three words here" (3 words) counts, so 3 < 4 should flag
        assert len(result) == 1
        assert result[0].value == "3"

    def test_empty_resolved_returns_none(self) -> None:
        """Empty resolved list means total=0; rule fires if min > 0."""
        rule = MinTotalWordsRule()
        params = MinTotalWordsParams(value=1)
        resolved: list[tuple[str, list[object]]] = []
        result = rule.check(rule_id="min_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1
        assert result[0].value == "0"

    def test_default_message_contains_counts(self) -> None:
        """Default message must mention actual and minimum counts."""
        rule = MinTotalWordsRule()
        params = MinTotalWordsParams(value=100)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]
        result = rule.check(rule_id="min_words", severity=Severity.ERROR, resolved=resolved, params=params)
        assert "5" in result[0].message  # actual
        assert "100" in result[0].message  # minimum
        assert result[0].severity == Severity.ERROR


class TestMaxTotalWordsRule:
    """Tests for MaxTotalWordsRule with flat schema params."""

    def test_flags_above_max(self) -> None:
        """Total above max must produce one issue."""
        rule = MaxTotalWordsRule()
        params = MaxTotalWordsParams(value=3)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]  # 5 words
        result = rule.check(rule_id="max_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1
        assert result[0].rule == "max_words"
        assert "5" in result[0].message  # actual count

    def test_passes_at_max(self) -> None:
        """Total equal to max must produce no issue."""
        rule = MaxTotalWordsRule()
        params = MaxTotalWordsParams(value=5)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]  # 5 words
        result = rule.check(rule_id="max_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_passes_below_max(self) -> None:
        """Total below max must produce no issue."""
        rule = MaxTotalWordsRule()
        params = MaxTotalWordsParams(value=10)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]  # 5 words
        result = rule.check(rule_id="max_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_skips_non_string_items(self) -> None:
        """Non-string items in resolved lists do not contribute to word count."""
        rule = MaxTotalWordsRule()
        params = MaxTotalWordsParams(value=2)
        resolved: list[tuple[str, list[object]]] = [("bullets", [42, None, {"key": "val"}, True, "three words here"])]
        result = rule.check(rule_id="max_words", severity=Severity.WARNING, resolved=resolved, params=params)
        # Only "three words here" (3 words) counts, so 3 > 2 should flag
        assert len(result) == 1
        assert result[0].value == "3"

    def test_empty_resolved_returns_none(self) -> None:
        """Empty resolved list means total=0; rule passes if max >= 0."""
        rule = MaxTotalWordsRule()
        params = MaxTotalWordsParams(value=0)
        resolved: list[tuple[str, list[object]]] = []
        result = rule.check(rule_id="max_words", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_default_message_contains_counts(self) -> None:
        """Default message must mention actual and maximum counts."""
        rule = MaxTotalWordsRule()
        params = MaxTotalWordsParams(value=1)
        resolved: list[tuple[str, list[object]]] = [("bullets", ["one two three", "four five"])]
        result = rule.check(rule_id="max_words", severity=Severity.ERROR, resolved=resolved, params=params)
        assert "5" in result[0].message  # actual
        assert "1" in result[0].message  # maximum
        assert result[0].severity == Severity.ERROR

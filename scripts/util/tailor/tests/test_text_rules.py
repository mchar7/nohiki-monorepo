"""Tests for banned_patterns rule -- flat schema API."""

from __future__ import annotations

from tailor.lint.content.rules.text_rules import BannedPatternsParams, BannedPatternsRule
from tailor.lint.models import BannedPattern, Severity


class TestBannedPatternsRule:
    """Tests for BannedPatternsRule with flat schema params."""

    def test_empty_patterns_rejected_at_config_time(self) -> None:
        """An empty patterns tuple is a no-op config bug; fail at validation, not silently."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BannedPatternsParams(patterns=())

    def test_flags_matching_text(self) -> None:
        rule = BannedPatternsRule()
        params = BannedPatternsParams(patterns=(BannedPattern(pattern="responsible for"),))
        resolved: list[tuple[str, list[object]]] = [("items", ["responsible for the system"])]
        result = rule.check(
            rule_id="content.banned_patterns", severity=Severity.WARNING, resolved=resolved, params=params
        )
        assert len(result) == 1
        assert result[0].rule == "content.banned_patterns"
        assert "responsible for" in result[0].message

    def test_case_insensitive_match(self) -> None:
        rule = BannedPatternsRule()
        params = BannedPatternsParams(patterns=(BannedPattern(pattern="responsible for"),))
        resolved: list[tuple[str, list[object]]] = [("items", ["Responsible for the system"])]
        result = rule.check(rule_id="test", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1

    def test_multiple_patterns_multiple_issues(self) -> None:
        rule = BannedPatternsRule()
        params = BannedPatternsParams(patterns=(BannedPattern(pattern="x"), BannedPattern(pattern="y")))
        resolved: list[tuple[str, list[object]]] = [("items", ["x y"])]
        result = rule.check(rule_id="test", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 2

    def test_non_string_items_skipped(self) -> None:
        rule = BannedPatternsRule()
        params = BannedPatternsParams(patterns=(BannedPattern(pattern="x"),))
        resolved: list[tuple[str, list[object]]] = [("items", [1, None, {}])]
        result = rule.check(rule_id="test", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_clean_text_returns_empty(self) -> None:
        rule = BannedPatternsRule()
        params = BannedPatternsParams(patterns=(BannedPattern(pattern="x"),))
        resolved: list[tuple[str, list[object]]] = [("items", ["clean"])]
        result = rule.check(rule_id="test", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_custom_message_used(self) -> None:
        rule = BannedPatternsRule()
        params = BannedPatternsParams(patterns=(BannedPattern(pattern="x", message="Custom!"),))
        resolved: list[tuple[str, list[object]]] = [("items", ["x"])]
        result = rule.check(rule_id="test", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result[0].message == "Custom!"

"""Tests for section rules -- flat schema API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.content.rules.section_rules import (
    BannedChildNamesParams,
    BannedChildNamesRule,
    FirstItemCapitalizationParams,
    FirstItemCapitalizationRule,
    MaxChildItemsParams,
    MaxChildItemsRule,
    MaxItemsParams,
    MaxItemsRule,
    MaxWordsPerItemParams,
    MaxWordsPerItemRule,
    MinItemsParams,
    MinItemsRule,
    MinWordsPerItemParams,
    MinWordsPerItemRule,
    UniqueOpeningWordsParams,
    UniqueOpeningWordsRule,
    VerbTenseParams,
    VerbTenseRule,
)
from tailor.lint.models import Severity

Resolved = list[tuple[str, list[object]]]


def _resolved(items: list[object], path: str = "items") -> Resolved:
    return [(path, items)]


# MinItemsRule


class TestMinItemsRule:
    """Tests for MinItemsRule."""

    def test_passes_when_count_at_min(self) -> None:
        rule = MinItemsRule()
        params = MinItemsParams(value=3)
        resolved: Resolved = _resolved(["a", "b", "c"])
        result = rule.check(
            rule_id="test.min_items",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_passes_when_count_above_min(self) -> None:
        rule = MinItemsRule()
        params = MinItemsParams(value=2)
        resolved: Resolved = _resolved(["a", "b", "c"])
        result = rule.check(
            rule_id="test.min_items",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_count_below_min(self) -> None:
        rule = MinItemsRule()
        params = MinItemsParams(value=5)
        resolved: Resolved = _resolved(["a", "b"])
        result = rule.check(
            rule_id="test.min_items",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].rule == "test.min_items"
        assert result[0].severity == Severity.ERROR
        assert result[0].value is not None
        assert "2" in result[0].value  # actual count

    def test_empty_list_fails_when_min_positive(self) -> None:
        rule = MinItemsRule()
        params = MinItemsParams(value=1)
        resolved: Resolved = _resolved([])
        result = rule.check(
            rule_id="test.min_items",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1


# MaxItemsRule


class TestMaxItemsRule:
    """Tests for MaxItemsRule."""

    def test_passes_when_count_at_max(self) -> None:
        rule = MaxItemsRule()
        params = MaxItemsParams(value=3)
        resolved: Resolved = _resolved(["a", "b", "c"])
        result = rule.check(
            rule_id="test.max_items",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_passes_when_count_below_max(self) -> None:
        rule = MaxItemsRule()
        params = MaxItemsParams(value=5)
        resolved: Resolved = _resolved(["a", "b", "c"])
        result = rule.check(
            rule_id="test.max_items",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_count_above_max(self) -> None:
        rule = MaxItemsRule()
        params = MaxItemsParams(value=2)
        resolved: Resolved = _resolved(["a", "b", "c"])
        result = rule.check(
            rule_id="test.max_items",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].rule == "test.max_items"


# MinWordsPerItemRule


class TestMinWordsPerItemRule:
    """Tests for MinWordsPerItemRule."""

    def test_passes_when_words_at_min(self) -> None:
        rule = MinWordsPerItemRule()
        params = MinWordsPerItemParams(value=3)
        resolved: Resolved = _resolved(["one two three"])
        result = rule.check(
            rule_id="test.min_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_words_below_min(self) -> None:
        rule = MinWordsPerItemRule()
        params = MinWordsPerItemParams(value=5)
        resolved: Resolved = _resolved(["one two"])
        result = rule.check(
            rule_id="test.min_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].value is not None
        assert "2" in result[0].value  # actual word count

    def test_non_string_items_skipped(self) -> None:
        rule = MinWordsPerItemRule()
        params = MinWordsPerItemParams(value=3)
        resolved: Resolved = _resolved([42, None, "one two three"])
        result = rule.check(
            rule_id="test.min_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Only "one two three" (3 words) passes
        assert result == []


# MaxWordsPerItemRule


class TestMaxWordsPerItemRule:
    """Tests for MaxWordsPerItemRule."""

    def test_passes_when_words_at_max(self) -> None:
        rule = MaxWordsPerItemRule()
        params = MaxWordsPerItemParams(value=3)
        resolved: Resolved = _resolved(["one two three"])
        result = rule.check(
            rule_id="test.max_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_words_above_max(self) -> None:
        rule = MaxWordsPerItemRule()
        params = MaxWordsPerItemParams(value=2)
        resolved: Resolved = _resolved(["one two three"])
        result = rule.check(
            rule_id="test.max_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].value is not None
        assert "3" in result[0].value


# UniqueOpeningWordsRule


class TestUniqueOpeningWordsRule:
    """Tests for UniqueOpeningWordsRule."""

    def test_passes_when_all_opening_words_unique(self) -> None:
        rule = UniqueOpeningWordsRule()
        params = UniqueOpeningWordsParams(enabled=True, scope="entry")
        resolved: Resolved = _resolved(["Led team", "Built system", "Designed API"])
        result = rule.check(
            rule_id="test.unique_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_duplicate_opening_words(self) -> None:
        rule = UniqueOpeningWordsRule()
        params = UniqueOpeningWordsParams(enabled=True, scope="entry")
        resolved: Resolved = _resolved(["Led team", "Led project", "Led initiative"])
        result = rule.check(
            rule_id="test.unique_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 2  # 2nd and 3rd items flagged

    def test_disabled_returns_empty(self) -> None:
        rule = UniqueOpeningWordsRule()
        params = UniqueOpeningWordsParams(enabled=False, scope="entry")
        resolved: Resolved = _resolved(["Led team", "Led project"])
        result = rule.check(
            rule_id="test.unique_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_scope_section_aggregates_across_paths(self) -> None:
        """Section scope flags duplicates across every resolved path in one call."""
        rule = UniqueOpeningWordsRule()
        params = UniqueOpeningWordsParams(enabled=True, scope="section")
        resolved: Resolved = [
            ("experience.entries[0].bullets", ["Led the migration", "Shipped the API"]),
            (
                "experience.entries[1].bullets",
                ["Led the launch", "Refactored the index"],
            ),
        ]
        result = rule.check(
            rule_id="test.unique_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].path == "experience.entries[1].bullets[0]"
        assert "Led" in result[0].message

    def test_scope_document_is_alias_for_section(self) -> None:
        """Document scope aggregates the same way as section in the flat schema."""
        rule = UniqueOpeningWordsRule()
        params = UniqueOpeningWordsParams(enabled=True, scope="document")
        resolved: Resolved = [
            ("a", ["Built system X"]),
            ("b", ["Built system Y"]),
        ]
        result = rule.check(
            rule_id="test.unique_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].path == "b[0]"

    def test_scope_entry_still_isolates_paths(self) -> None:
        """Entry scope (default) does NOT flag the same opener across different paths."""
        rule = UniqueOpeningWordsRule()
        params = UniqueOpeningWordsParams(enabled=True, scope="entry")
        resolved: Resolved = [
            ("a", ["Led the migration"]),
            ("b", ["Led the launch"]),
        ]
        result = rule.check(
            rule_id="test.unique_words",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_invalid_scope_value_rejected_at_params_level(self) -> None:
        """Scopes outside the allowed Literal are rejected by Pydantic before reaching the rule."""
        rule = UniqueOpeningWordsRule()
        resolved: Resolved = _resolved(["Led team"])
        with pytest.raises(ValidationError):
            # ``model_validate`` takes an untyped mapping, so the invalid scope is
            # exercised at Pydantic's validation layer (not the static call).
            UniqueOpeningWordsParams.model_validate({"enabled": True, "scope": "paragraph"})
        # Sanity: the rule happily accepts the three valid scopes.
        for valid_scope in ("entry", "section", "document"):
            validated = UniqueOpeningWordsParams.model_validate({"enabled": True, "scope": valid_scope})
            rule.check(
                rule_id="test.unique_words",
                severity=Severity.WARNING,
                resolved=resolved,
                params=validated,
            )


# VerbTenseRule


class TestVerbTenseRule:
    """Tests for VerbTenseRule."""

    def test_passes_with_past_tense_verbs(self) -> None:
        rule = VerbTenseRule()
        params = VerbTenseParams(require="past")
        resolved: Resolved = _resolved(["Led team", "Built system", "Designed API"])
        result = rule.check(
            rule_id="test.verb_tense",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_with_present_tense_verbs(self) -> None:
        rule = VerbTenseRule()
        params = VerbTenseParams(require="past")
        resolved: Resolved = _resolved(["Lead team", "Build system"])
        result = rule.check(
            rule_id="test.verb_tense",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 2

    def test_non_string_items_skipped(self) -> None:
        rule = VerbTenseRule()
        params = VerbTenseParams(require="past")
        resolved: Resolved = _resolved([42, None, "Led team"])
        result = rule.check(
            rule_id="test.verb_tense",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []


# MaxChildItemsRule


class TestMaxChildItemsRule:
    """Tests for MaxChildItemsRule."""

    def test_passes_when_child_count_at_max(self) -> None:
        rule = MaxChildItemsRule()
        params = MaxChildItemsParams(child_key="skills", value=3)
        resolved: Resolved = _resolved([{"skills": ["a", "b", "c"]}])
        result = rule.check(
            rule_id="test.max_child",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_child_count_above_max(self) -> None:
        rule = MaxChildItemsRule()
        params = MaxChildItemsParams(child_key="skills", value=2)
        resolved: Resolved = _resolved([{"skills": ["a", "b", "c"]}])
        result = rule.check(
            rule_id="test.max_child",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_missing_child_key_skipped(self) -> None:
        rule = MaxChildItemsRule()
        params = MaxChildItemsParams(child_key="skills", value=2)
        resolved: Resolved = _resolved([{"other": ["a", "b", "c"]}])
        result = rule.check(
            rule_id="test.max_child",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_non_list_child_skipped(self) -> None:
        rule = MaxChildItemsRule()
        params = MaxChildItemsParams(child_key="skills", value=2)
        resolved: Resolved = _resolved([{"skills": "not a list"}])
        result = rule.check(
            rule_id="test.max_child",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []


# BannedChildNamesRule


class TestBannedChildNamesRule:
    """Tests for BannedChildNamesRule."""

    def test_empty_patterns_rejected_at_config_time(self) -> None:
        """An empty patterns tuple is a no-op config bug; fail at validation, not silently."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BannedChildNamesParams(name_key="name", patterns=())

    def test_fails_when_name_matches_banned_pattern(self) -> None:
        rule = BannedChildNamesRule()
        params = BannedChildNamesParams(name_key="name", patterns=("Soft Skills",))
        resolved: Resolved = _resolved([{"name": "Soft Skills"}])
        result = rule.check(
            rule_id="test.banned_names",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "Soft Skills" in result[0].message

    def test_case_insensitive_matching(self) -> None:
        rule = BannedChildNamesRule()
        params = BannedChildNamesParams(name_key="name", patterns=("soft skills",))
        resolved: Resolved = _resolved([{"name": "SOFT SKILLS"}])
        result = rule.check(
            rule_id="test.banned_names",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_missing_name_key_skipped(self) -> None:
        rule = BannedChildNamesRule()
        params = BannedChildNamesParams(name_key="name", patterns=("Bad",))
        resolved: Resolved = _resolved([{"other": "value"}])
        result = rule.check(
            rule_id="test.banned_names",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_non_string_name_skipped(self) -> None:
        rule = BannedChildNamesRule()
        params = BannedChildNamesParams(name_key="name", patterns=("Bad",))
        resolved: Resolved = _resolved([{"name": 123}])
        result = rule.check(
            rule_id="test.banned_names",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_invalid_regex_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            BannedChildNamesParams(name_key="name", patterns=("[invalid",))


# FirstItemCapitalizationRule


class TestFirstItemCapitalizationRule:
    """Tests for FirstItemCapitalizationRule."""

    def test_passes_when_first_item_capitalized(self) -> None:
        rule = FirstItemCapitalizationRule()
        params = FirstItemCapitalizationParams(child_key=None)
        resolved: Resolved = _resolved(["Capitalized item"])
        result = rule.check(
            rule_id="test.capitalization",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_first_item_lowercase(self) -> None:
        rule = FirstItemCapitalizationRule()
        params = FirstItemCapitalizationParams(child_key=None)
        resolved: Resolved = _resolved(["lowercase item"])
        result = rule.check(
            rule_id="test.capitalization",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "lowercase" in result[0].message.lower()

    def test_with_child_key_checks_nested(self) -> None:
        rule = FirstItemCapitalizationRule()
        params = FirstItemCapitalizationParams(child_key="items")
        resolved: Resolved = _resolved([{"items": ["Capitalized"]}])
        result = rule.check(
            rule_id="test.capitalization",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_with_child_key_fails_on_lowercase(self) -> None:
        rule = FirstItemCapitalizationRule()
        params = FirstItemCapitalizationParams(child_key="items")
        resolved: Resolved = _resolved([{"items": ["lowercase"]}])
        result = rule.check(
            rule_id="test.capitalization",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_empty_list_returns_empty(self) -> None:
        rule = FirstItemCapitalizationRule()
        params = FirstItemCapitalizationParams(child_key=None)
        resolved: Resolved = _resolved([])
        result = rule.check(
            rule_id="test.capitalization",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_non_string_first_item_skipped(self) -> None:
        rule = FirstItemCapitalizationRule()
        params = FirstItemCapitalizationParams(child_key=None)
        resolved: Resolved = _resolved([42, "Capitalized"])
        result = rule.check(
            rule_id="test.capitalization",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

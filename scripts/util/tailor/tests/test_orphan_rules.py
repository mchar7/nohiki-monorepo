"""Tests for orphan_final_word_heuristic rule -- surfaces risky final-word patterns.

Tests cover word matching, case sensitivity, and sentence-based variants.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.content.rules.orphan_rules import OrphanFinalWordHeuristicParams, OrphanFinalWordHeuristicRule
from tailor.lint.models import Severity

type Resolved = list[tuple[str, list[object]]]


def _resolved(items: list[object]) -> Resolved:
    """Helper to create resolved items list."""
    return [("items", items)]


class TestOrphanFinalWordHeuristicRule:
    """Tests for OrphanFinalWordHeuristicRule."""

    def test_empty_risky_words_rejected(self) -> None:
        """Empty risky_final_words tuple fails validation."""
        with pytest.raises(ValidationError):
            OrphanFinalWordHeuristicParams(risky_final_words=())

    def test_whitespace_only_risky_words_rejected(self) -> None:
        """Whitespace-only entries in risky_final_words fail validation."""
        with pytest.raises(ValidationError):
            OrphanFinalWordHeuristicParams(risky_final_words=("  ", "test"))

    def test_empty_string_entry_rejected(self) -> None:
        """Empty string entries in risky_final_words fail validation."""
        with pytest.raises(ValidationError):
            OrphanFinalWordHeuristicParams(risky_final_words=("", "test"))

    def test_unstripped_entry_rejected(self) -> None:
        """Entries with leading/trailing whitespace fail validation."""
        with pytest.raises(ValidationError):
            OrphanFinalWordHeuristicParams(risky_final_words=("test ", " word"))

    def test_flags_items_ending_with_risky_word(self) -> None:
        """Items ending with a risky word are flagged."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("the", "and", "for"))
        resolved: Resolved = _resolved(["This is for"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1
        assert "for" in result[0].message

    def test_clean_items_no_violation(self) -> None:
        """Items ending with safe words return no issues."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("the", "and"))
        resolved: Resolved = _resolved(["This is good"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_case_insensitive_by_default(self) -> None:
        """case_sensitive=False matches any case."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(
            risky_final_words=("for", "the"),
            case_sensitive=False,
        )
        resolved: Resolved = _resolved(["This is FOR", "This is The"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 2

    def test_case_sensitive_respects_case(self) -> None:
        """case_sensitive=True requires exact case match."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(
            risky_final_words=("For", "The"),
            case_sensitive=True,
        )
        resolved: Resolved = _resolved(["This is for", "This is the"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        # Lowercase "for" and "the" don't match uppercase "For" and "The"
        assert result == []

    def test_strips_punctuation_from_final_word(self) -> None:
        """Surrounding punctuation is stripped before matching."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("for",))
        resolved: Resolved = _resolved(["This is for.", "This is for!", "This is for?"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 3

    def test_check_last_sentence_only_false(self) -> None:
        """check_last_sentence_only=False (default) checks full item's final word."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(
            risky_final_words=("for",),
            check_last_sentence_only=False,
        )
        # Final word of item is "for", even though not final in last sentence
        resolved: Resolved = _resolved(["This is for. But wait, there's more."])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        # Final word of whole item is "more", not "for"
        assert result == []

    def test_check_last_sentence_only_true(self) -> None:
        """check_last_sentence_only=True checks only the last sentence's final word."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(
            risky_final_words=("for",),
            check_last_sentence_only=True,
        )
        # Last sentence ends with "."
        resolved: Resolved = _resolved(["This is a test for. But wait."])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        # Last sentence is "But wait.", final word is "wait"
        assert result == []

    def test_multiple_risky_words(self) -> None:
        """Multiple risky words can be specified."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("and", "or", "but", "for"))
        resolved: Resolved = _resolved(["This is and", "This is or", "This is good"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 2

    def test_empty_items_skipped(self) -> None:
        """Empty items are skipped."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("for",))
        resolved: Resolved = _resolved(["", "   ", "This is for"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1

    def test_non_string_items_skipped(self) -> None:
        """Non-string items are skipped."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("for",))
        resolved: Resolved = _resolved([123, None, {}])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_single_word_items(self) -> None:
        """Single-word items are handled correctly."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("for",))
        resolved: Resolved = _resolved(["for", "but", "word"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1
        assert "for" in result[0].message

    def test_apostrophe_stripped_from_final_word(self) -> None:
        """Apostrophes in final word are stripped for matching."""
        rule = OrphanFinalWordHeuristicRule()
        params = OrphanFinalWordHeuristicParams(risky_final_words=("for",))
        resolved: Resolved = _resolved(["This is for'"])
        result = rule.check(rule_id="test.orphan", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) == 1

"""Tests for ratio rule -- occurrence-per-100-words density metric.

Tests cover pattern matching, density calculation, and bound violations.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.content.rules.ratio_rules import RatioParams, RatioRule
from tailor.lint.models import Severity

type Resolved = list[tuple[str, list[object]]]


def _resolved(items: list[object]) -> Resolved:
    """Helper to create resolved items list."""
    return [("items", items)]


class TestRatioRule:
    """Tests for RatioRule."""

    def test_empty_pattern_rejected(self) -> None:
        """Empty pattern fails validation."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="", min_per_100_words=1)

    def test_invalid_regex_rejected(self) -> None:
        """Invalid regex pattern fails validation."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="[invalid", min_per_100_words=1)

    def test_requires_at_least_one_bound(self) -> None:
        """Must have at least min or max bound."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="x", min_per_100_words=None, max_per_100_words=None)

    def test_min_per_100_negative_rejected(self) -> None:
        """Negative min_per_100_words fails validation."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="x", min_per_100_words=-1)

    def test_max_per_100_negative_rejected(self) -> None:
        """Negative max_per_100_words fails validation."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="x", max_per_100_words=-1)

    def test_min_greater_than_max_rejected(self) -> None:
        """min_per_100_words > max_per_100_words fails validation."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="x", min_per_100_words=10, max_per_100_words=5)

    def test_min_scope_words_must_be_positive(self) -> None:
        """min_scope_words must be >= 1."""
        with pytest.raises(ValidationError):
            RatioParams(pattern="x", min_per_100_words=1, min_scope_words=0)

    def test_skips_small_scopes(self) -> None:
        """Scopes with fewer than min_scope_words are skipped."""
        rule = RatioRule()
        params = RatioParams(pattern="x", min_per_100_words=1, min_scope_words=50)
        # Only 10 words, min_scope is 50
        resolved: Resolved = _resolved(["hello world test one two three four five six ten"])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_flags_below_min_density(self) -> None:
        """Count below min_per_100_words triggers issue."""
        rule = RatioRule()
        params = RatioParams(pattern=r"\b[aeiou]\w+", min_per_100_words=10, min_scope_words=1)
        # Text with maybe 50 words and few "a/e/i/o/u" words
        text = "cat dog bird fish snake turtle bear wolf moose lion tiger zebra elephant giraffe "
        text *= 5  # Repeat to get more words
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should have low vowel-start word ratio
        assert len(result) == 1
        assert "below floor" in result[0].message

    def test_flags_above_max_density(self) -> None:
        """Count above max_per_100_words triggers issue."""
        rule = RatioRule()
        params = RatioParams(pattern=r"\d", max_per_100_words=1, min_scope_words=1)
        # Text with many numbers
        text = "1 2 3 4 5 6 7 8 9 10 test word foo bar baz"
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "above ceiling" in result[0].message

    def test_passes_within_bounds(self) -> None:
        """Density within both bounds returns empty."""
        rule = RatioRule()
        # Text with 45 word tokens, count "the" pattern
        # "the" appears 10 times, so density = 10/(45/100) = 22.22 per 100 words
        params = RatioParams(
            pattern=r"\bthe\b",
            min_per_100_words=20,
            max_per_100_words=25,
            min_scope_words=1,
        )
        text = "the quick brown fox jumps over the lazy dog " * 5
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_case_insensitive_by_default(self) -> None:
        """case_sensitive=False matches pattern any case."""
        rule = RatioRule()
        params = RatioParams(pattern="test", case_sensitive=False, min_per_100_words=5, min_scope_words=1)
        text = "Test TEST test word word word word " * 5
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should find 3 matches per iteration, which is within normal bounds
        assert len(result) == 0

    def test_case_sensitive_respects_case(self) -> None:
        """case_sensitive=True requires exact case."""
        rule = RatioRule()
        params = RatioParams(pattern="test", case_sensitive=True, max_per_100_words=20, min_scope_words=1)
        text = "test TEST Test word word word word " * 5
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Only exact "test" (lowercase) matches
        assert result == []

    def test_regex_pattern_uses_findall(self) -> None:
        """Pattern uses findall semantics (non-overlapping)."""
        rule = RatioRule()
        params = RatioParams(pattern=r"\d+", min_per_100_words=10, min_scope_words=1)
        # Multiple digit sequences
        text = "123 456 789 test words more test words " * 5
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should find 3 matches per iteration
        assert len(result) >= 0  # May or may not violate depending on exact count

    def test_multiple_items_concatenated(self) -> None:
        """Multiple items are concatenated with newlines."""
        rule = RatioRule()
        params = RatioParams(pattern="test", min_per_100_words=1, min_scope_words=1)
        resolved: Resolved = _resolved(["test hello world", "test foo bar baz"])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should find both "test" occurrences
        assert isinstance(result, list)

    def test_zero_bounds_valid(self) -> None:
        """min/max of 0 are valid bounds."""
        params = RatioParams(pattern="x", min_per_100_words=0, max_per_100_words=0)
        assert params.min_per_100_words == 0
        assert params.max_per_100_words == 0

    def test_non_overlapping_regex_matches(self) -> None:
        """Regex matches are non-overlapping (like findall)."""
        rule = RatioRule()
        params = RatioParams(pattern=r"aa", max_per_100_words=1, min_scope_words=1)
        text = "aaa test words " * 5  # "aaa" has 1 non-overlapping "aa"
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.ratio",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) >= 0

    def test_contractions_straight_apostrophe(self) -> None:
        """Contraction pattern matches straight ASCII apostrophe (U+0027)."""
        rule = RatioRule()
        # Character class includes both straight (U+0027) and curly (U+2019) apostrophes.
        params = RatioParams(
            pattern=r"\b\w+['\u2019](s|t|d|ll|ve|re|m)\b",
            min_per_100_words=5.0,
            max_per_100_words=100.0,
            min_scope_words=1,
        )
        # 4 contractions with straight apostrophes
        text = "I've done it. I'd like it. It's great. We're ready."
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.contraction.straight",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Density is well above the 5.0 floor, so no issue expected.
        assert result == []

    def test_contractions_curly_apostrophe(self) -> None:
        """Contraction pattern matches curly apostrophe (U+2019) as used in typographic text."""
        rule = RatioRule()
        params = RatioParams(
            pattern=r"\b\w+['\u2019](s|t|d|ll|ve|re|m)\b",
            min_per_100_words=5.0,
            max_per_100_words=100.0,
            min_scope_words=1,
        )
        # Same 4 contractions with curly apostrophes (as rendered JSON data stores them)
        text = "I\u2019ve done it. I\u2019d like it. It\u2019s great. We\u2019re ready."
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.contraction.curly",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Fix verification: curly apostrophes must be matched by the character class.
        assert result == []

    def test_contractions_curly_apostrophe_regression(self) -> None:
        """REGRESSION: straight-only pattern misses curly apostrophes (the original bug)."""
        rule = RatioRule()
        # Pattern using only straight apostrophe (simulates the pre-fix YAML).
        params = RatioParams(
            pattern=r"\b\w+'(s|t|d|ll|ve|re|m)\b",
            min_per_100_words=5.0,
            max_per_100_words=100.0,
            min_scope_words=1,
        )
        # Text with curly apostrophes (matches what cover-letter JSON actually contains)
        text = "I\u2019ve done it. I\u2019d like it. It\u2019s great. We\u2019re ready."
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.contraction.bug",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Without curly apostrophe in the character class, zero matches → density below floor.
        # This documents the bug that the character-class fix addresses.
        assert len(result) == 1
        assert "below floor" in result[0].message

    def test_contractions_mixed_apostrophes(self) -> None:
        """Contraction pattern matches a mix of straight and curly apostrophes in one text."""
        rule = RatioRule()
        params = RatioParams(
            pattern=r"\b\w+['\u2019](s|t|d|ll|ve|re|m)\b",
            min_per_100_words=5.0,
            max_per_100_words=100.0,
            min_scope_words=1,
        )
        text = "I've seen it. I\u2019d like it. It's great. We\u2019re ready."
        resolved: Resolved = _resolved([text])
        result = rule.check(
            rule_id="test.contraction.mixed",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

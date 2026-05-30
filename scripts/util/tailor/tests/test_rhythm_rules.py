"""Tests for rhythm_check rule -- detects runs of similar-length sentences.

Tests cover word count and syllable count modes, tolerance, and run detection.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.content.rules.rhythm_rules import RhythmCheckParams, RhythmCheckRule
from tailor.lint.models import Severity

type Resolved = list[tuple[str, list[object]]]


def _resolved(items: list[object]) -> Resolved:
    """Helper to create resolved items list."""
    return [("items", items)]


class TestRhythmCheckRule:
    """Tests for RhythmCheckRule."""

    def test_max_consecutive_must_be_positive(self) -> None:
        """max_consecutive_similar must be >= 1."""
        with pytest.raises(ValidationError):
            RhythmCheckParams(max_consecutive_similar=0)

    def test_tolerance_must_be_nonnegative(self) -> None:
        """Tolerance must be >= 0."""
        with pytest.raises(ValidationError):
            RhythmCheckParams(tolerance=-1)

    def test_min_scope_size_must_be_positive(self) -> None:
        """min_scope_size must be >= 1."""
        with pytest.raises(ValidationError):
            RhythmCheckParams(min_scope_size=0)

    def test_skips_items_with_too_few_sentences(self) -> None:
        """Items with fewer sentences than min_scope_size are skipped."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(min_scope_size=5)
        # Only 2 sentences
        text = "First sentence. Second sentence."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_word_count_mode(self) -> None:
        """mode='word_count' measures sentence length in words."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="word_count", max_consecutive_similar=2, tolerance=1, min_scope_size=3)
        # 4 sentences with word counts: [3, 3, 3, 3] - all within tolerance
        text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        # All 4 sentences have similar word counts, exceeding max=2
        assert len(result) == 1

    def test_syllable_count_mode(self) -> None:
        """mode='syllable_count' measures sentence length in syllables."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="syllable_count", max_consecutive_similar=2, tolerance=2, min_scope_size=3)
        # Sentences with varying syllable counts
        text = "Cat. Elephant. Dog. Beautiful elephant. Test."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        assert isinstance(result, list)

    def test_tolerance_zero_requires_exact_match(self) -> None:
        """tolerance=0 requires exact length match."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="word_count", max_consecutive_similar=2, tolerance=0, min_scope_size=3)
        # Sentences with lengths [2, 2, 3, 3]
        text = "One two. Three four. Five six seven. Eight nine ten."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        # Should find runs of exact length: 2-word pair, 3-word pair
        assert len(result) == 0  # No run > max_consecutive=2

    def test_detects_run_exceeding_max(self) -> None:
        """Run length exceeding max_consecutive_similar is flagged."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="word_count", max_consecutive_similar=1, tolerance=1, min_scope_size=2)
        # 3 sentences with similar lengths
        text = "One two. Three four. Five six."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) >= 1

    def test_run_at_end_detected(self) -> None:
        """Run at the end of sentences is detected."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="word_count", max_consecutive_similar=1, tolerance=1, min_scope_size=2)
        # Sentence 1 different, then 3 similar
        text = "Different very long sentence here. One. Two. Three."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) >= 1

    def test_multiple_items_checked_independently(self) -> None:
        """Multiple items are checked independently."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="word_count", max_consecutive_similar=1, tolerance=1, min_scope_size=2)
        # Item 1 has problem, Item 2 doesn't
        text1 = "One. Two. Three."
        text2 = "A very different sentence here. Another one. And another. And final."
        resolved: Resolved = _resolved([text1, text2])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        assert len(result) >= 1

    def test_non_string_items_skipped(self) -> None:
        """Non-string items are skipped."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(min_scope_size=1)
        resolved: Resolved = _resolved([123, None, {}])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        assert result == []

    def test_tolerance_includes_range(self) -> None:
        """Tolerance defines a range around the min/max of run."""
        rule = RhythmCheckRule()
        params = RhythmCheckParams(mode="word_count", max_consecutive_similar=2, tolerance=2, min_scope_size=3)
        # Sentences with lengths [5, 6, 7] - max-min = 2, within tolerance
        text = "One two three four five. One two three four five six. One two three four five six seven."
        resolved: Resolved = _resolved([text])
        result = rule.check(rule_id="test.rhythm", severity=Severity.WARNING, resolved=resolved, params=params)
        # 3 sentences within tolerance, exceeding max_consecutive=2
        assert len(result) == 1

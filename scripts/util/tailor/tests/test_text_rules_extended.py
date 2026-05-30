"""Tests for text rules: banned_openers, max_structural_punctuation, etc.

Tests cover flat schema APIs for rules:
  - banned_openers
  - max_structural_punctuation_per_sentence
  - max_consecutive_opener
  - mention_count
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tailor.lint.content.rules.text_rules import (
    BannedOpenersParams,
    BannedOpenersRule,
    MaxConsecutiveOpenerParams,
    MaxConsecutiveOpenerRule,
    MaxStructuralPunctuationPerSentenceParams,
    MaxStructuralPunctuationPerSentenceRule,
    MentionCountParams,
    MentionCountRule,
)
from tailor.lint.models import BannedPattern, Severity

type Resolved = list[tuple[str, list[object]]]


def _resolved(items: list[object], path: str = "items") -> Resolved:
    """Helper to create resolved items list."""
    return [(path, items)]


# BannedOpenersRule


class TestBannedOpenersRule:
    """Tests for BannedOpenersRule."""

    def test_empty_patterns_rejected_at_config_time(self) -> None:
        """Empty patterns tuple fails validation."""
        with pytest.raises(ValidationError):
            BannedOpenersParams(patterns=(), scope="item")

    def test_item_scope_matches_opening_tokens(self) -> None:
        """Item scope: flags pattern in opening tokens."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            scope="item",
            max_token_check=1,
            patterns=(BannedPattern(pattern="Indeed"),),
        )
        resolved: Resolved = _resolved(["Indeed this is true"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "Indeed" in result[0].message

    def test_item_scope_no_match_clean(self) -> None:
        """Item scope: clean text returns no issues."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            scope="item",
            max_token_check=1,
            patterns=(BannedPattern(pattern="Indeed"),),
        )
        resolved: Resolved = _resolved(["Clean text here"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_sentence_scope_checks_each_sentence(self) -> None:
        """Sentence scope: checks opening tokens of each sentence."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            scope="sentence",
            max_token_check=1,
            patterns=(BannedPattern(pattern="Moreover"),),
        )
        # First sentence passes, second sentence violates
        resolved: Resolved = _resolved(["This is good. Moreover this is bad."])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "sentence[1]" in result[0].path

    def test_case_insensitive_by_default(self) -> None:
        """case_sensitive=False (default) matches any case."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            case_sensitive=False,
            max_token_check=1,
            patterns=(BannedPattern(pattern="indeed"),),
        )
        resolved: Resolved = _resolved(["INDEED this is true"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_case_sensitive_respects_case(self) -> None:
        """case_sensitive=True requires exact case match."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            case_sensitive=True,
            max_token_check=1,
            patterns=(BannedPattern(pattern="Indeed"),),
        )
        resolved: Resolved = _resolved(["indeed this is true"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_max_token_check_joins_multiple_tokens(self) -> None:
        """max_token_check=2 joins first 2 tokens before matching."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            max_token_check=2,
            patterns=(BannedPattern(pattern="It seems"),),
        )
        resolved: Resolved = _resolved(["It seems like a good idea"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_max_token_check_less_than_available_tokens(self) -> None:
        """max_token_check limits tokens joined, even if more are available."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            max_token_check=1,
            patterns=(BannedPattern(pattern="It seems"),),
        )
        resolved: Resolved = _resolved(["It seems like a good idea"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should not match because only "It" is checked, not "It seems"
        assert result == []

    def test_max_token_check_zero_rejected(self) -> None:
        """max_token_check must be >= 1."""
        with pytest.raises(ValidationError):
            BannedOpenersParams(max_token_check=0, patterns=(BannedPattern(pattern="x"),))

    def test_non_string_items_skipped(self) -> None:
        """Non-string items are skipped silently."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            patterns=(BannedPattern(pattern="Indeed"),),
        )
        resolved: Resolved = _resolved([123, None, {}])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_custom_message_preserved(self) -> None:
        """Per-pattern message override is used in issue."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            patterns=(BannedPattern(pattern="Indeed", message="Use 'Moreover' instead"),),
        )
        resolved: Resolved = _resolved(["Indeed this is true"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result[0].message == "Use 'Moreover' instead"

    def test_multiple_patterns_multiple_issues(self) -> None:
        """Multiple patterns generate one issue per match per item."""
        rule = BannedOpenersRule()
        params = BannedOpenersParams(
            patterns=(BannedPattern(pattern="x"), BannedPattern(pattern="y")),
        )
        resolved: Resolved = _resolved(["x and y here"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # "x" matches, "y" doesn't (it's not first token)
        assert len(result) == 1


# MaxStructuralPunctuationPerSentenceRule


class TestMaxStructuralPunctuationPerSentenceRule:
    """Tests for MaxStructuralPunctuationPerSentenceRule."""

    def test_passes_when_count_at_max(self) -> None:
        """Sentence with punctuation count == max passes."""
        rule = MaxStructuralPunctuationPerSentenceRule()
        params = MaxStructuralPunctuationPerSentenceParams(max=2)
        # Semicolon and colon count = 2
        resolved: Resolved = _resolved(["First part; second part: end."])
        result = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_fails_when_count_exceeds_max(self) -> None:
        """Sentence with count > max fails."""
        rule = MaxStructuralPunctuationPerSentenceRule()
        params = MaxStructuralPunctuationPerSentenceParams(max=1)
        # Semicolon and colon = 2, max is 1
        resolved: Resolved = _resolved(["Part one; part two: end."])
        result = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "2" in result[0].message
        assert "max 1" in result[0].message

    def test_default_punctuation_semicolon_colon(self) -> None:
        """Default punctuation set is {';', ':'}."""
        rule = MaxStructuralPunctuationPerSentenceRule()
        params = MaxStructuralPunctuationPerSentenceParams(max=0)
        resolved: Resolved = _resolved(["One; two."])
        result = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_custom_punctuation_set(self) -> None:
        """Custom punctuation set can be provided."""
        rule = MaxStructuralPunctuationPerSentenceRule()
        params = MaxStructuralPunctuationPerSentenceParams(max=1, punctuation=frozenset({"!", "?"}))
        # Two exclamation marks in one sentence, max 1
        resolved: Resolved = _resolved(["Wait! What!"])
        result = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Each sentence has 1 exclamation mark, which equals max, so no violation
        assert result == []

        # Now test with actual violation: 2 exclamation marks in one sentence
        resolved2: Resolved = _resolved(["Wait!! What!"])
        result2 = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved2,
            params=params,
        )
        assert len(result2) == 1

    def test_empty_punctuation_rejected(self) -> None:
        """Empty punctuation set fails validation."""
        with pytest.raises(ValidationError):
            MaxStructuralPunctuationPerSentenceParams(max=1, punctuation=frozenset())

    def test_multichar_punctuation_rejected(self) -> None:
        """Multi-char entries in punctuation fail validation."""
        with pytest.raises(ValidationError):
            MaxStructuralPunctuationPerSentenceParams(max=1, punctuation=frozenset({";;", ":"}))

    def test_multiple_sentences_checked_independently(self) -> None:
        """Each sentence is checked independently."""
        rule = MaxStructuralPunctuationPerSentenceRule()
        params = MaxStructuralPunctuationPerSentenceParams(max=1)
        # First sentence ok (1 semicolon), second sentence violates (2 semicolons)
        resolved: Resolved = _resolved(["Part; end. Another; one; two."])
        result = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "sentence[1]" in result[0].path

    def test_non_string_items_skipped(self) -> None:
        """Non-string items are skipped."""
        rule = MaxStructuralPunctuationPerSentenceRule()
        params = MaxStructuralPunctuationPerSentenceParams(max=0)
        resolved: Resolved = _resolved([123, None, {}])
        result = rule.check(
            rule_id="test.punct",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []


# MaxConsecutiveOpenerRule


class TestMaxConsecutiveOpenerRule:
    """Tests for MaxConsecutiveOpenerRule."""

    def test_passes_when_no_consecutive_matches(self) -> None:
        """No runs exceeding max_consecutive returns empty."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="I", max_consecutive=2)
        resolved: Resolved = _resolved(["I did this", "You did that", "I did again"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_detects_run_exceeding_max(self) -> None:
        """Run length > max_consecutive triggers issue."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="I", max_consecutive=2)
        resolved: Resolved = _resolved(["I did this", "I did that", "I did more"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "3" in result[0].message

    def test_case_insensitive_by_default(self) -> None:
        """case_sensitive=False matches any case."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="i", max_consecutive=1, case_sensitive=False)
        resolved: Resolved = _resolved(["I did this", "I did that"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_case_sensitive_respects_case(self) -> None:
        """case_sensitive=True requires exact case."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="I", max_consecutive=1, case_sensitive=True)
        resolved: Resolved = _resolved(["i did this", "i did that"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_regex_matching(self) -> None:
        """is_regex=True enables regex fullmatch on first token."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="[A-Z][a-z]+", is_regex=True, max_consecutive=1, case_sensitive=True)
        # All three items start with capital letter followed by lowercase (Apple, Banana, Cherry)
        resolved: Resolved = _resolved(["Apple is good", "Banana is good", "Cherry is good"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "3" in result[0].message

    def test_invalid_regex_rejected(self) -> None:
        """Invalid regex fails at validation."""
        with pytest.raises(ValidationError):
            MaxConsecutiveOpenerParams(token="[invalid", is_regex=True, max_consecutive=1)

    def test_sentence_granularity(self) -> None:
        """granularity='sentence' checks sentences instead of items."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="I", max_consecutive=1, granularity="sentence")
        # Single item with multiple sentences, first two start with "I"
        resolved: Resolved = _resolved(["I did this. I also did that. You did this."])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_non_string_items_skipped(self) -> None:
        """Non-string items are skipped."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="I", max_consecutive=1)
        resolved: Resolved = _resolved([123, None, {}])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_max_consecutive_must_be_positive(self) -> None:
        """max_consecutive must be >= 1."""
        with pytest.raises(ValidationError):
            MaxConsecutiveOpenerParams(token="I", max_consecutive=0)

    def test_empty_token_rejected(self) -> None:
        """Empty token string fails validation."""
        with pytest.raises(ValidationError):
            MaxConsecutiveOpenerParams(token="", max_consecutive=1)

    def test_run_at_end_of_list_detected(self) -> None:
        """Run at the end of item list is detected."""
        rule = MaxConsecutiveOpenerRule()
        params = MaxConsecutiveOpenerParams(token="I", max_consecutive=1)
        resolved: Resolved = _resolved(["You did this", "I did that", "I did more"])
        result = rule.check(
            rule_id="test.openers",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "items[1]" in result[0].path


# MentionCountRule


class TestMentionCountRule:
    """Tests for MentionCountRule."""

    def test_empty_target_rejected(self) -> None:
        """Empty target fails validation."""
        with pytest.raises(ValidationError):
            MentionCountParams(target="", min=1)

    def test_requires_at_least_one_bound(self) -> None:
        """Must have at least min or max bound."""
        with pytest.raises(ValidationError):
            MentionCountParams(target="x", min=None, max=None)

    def test_min_bound_violation(self) -> None:
        """Count below min triggers issue."""
        rule = MentionCountRule()
        params = MentionCountParams(target="Acme", min=2)
        resolved: Resolved = _resolved(["Worked at Acme for one year."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "1 times (min 2)" in result[0].message

    def test_max_bound_violation(self) -> None:
        """Count above max triggers issue."""
        rule = MentionCountRule()
        params = MentionCountParams(target="Acme", max=1)
        resolved: Resolved = _resolved(["Acme is great. Acme hired me."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert "2 times (max 1)" in result[0].message

    def test_both_bounds_can_violate(self) -> None:
        """When both min and max are set, violations are reported appropriately."""
        rule = MentionCountRule()
        params = MentionCountParams(target="Acme", min=1, max=1)
        resolved: Resolved = _resolved(["Acme one. Acme two. Acme three."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Count is 3, max is 1, so max violation
        assert len(result) == 1
        assert "3 times (max 1)" in result[0].message

    def test_passes_within_bounds(self) -> None:
        """Count within both bounds returns empty."""
        rule = MentionCountRule()
        params = MentionCountParams(target="Acme", min=1, max=3)
        resolved: Resolved = _resolved(["Acme is great. Acme hired me."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_case_insensitive_by_default(self) -> None:
        """case_sensitive=False matches any case."""
        rule = MentionCountRule()
        params = MentionCountParams(target="acme", case_sensitive=False, min=2)
        resolved: Resolved = _resolved(["Acme and ACME are both great."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should count both "Acme" and "ACME" as 2 matches
        assert result == []

    def test_case_sensitive_respects_case(self) -> None:
        """case_sensitive=True requires exact case match."""
        rule = MentionCountRule()
        params = MentionCountParams(target="Acme", case_sensitive=True, min=2)
        resolved: Resolved = _resolved(["Acme and acme are mentioned."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should only count "Acme", not "acme"
        assert len(result) == 1
        assert "1 times (min 2)" in result[0].message

    def test_regex_matching(self) -> None:
        """is_regex=True treats target as regex."""
        rule = MentionCountRule()
        params = MentionCountParams(target=r"\d+", is_regex=True, max=1)
        resolved: Resolved = _resolved(["I worked 3 years and 5 months."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should find "3" and "5" (2 matches), max is 1
        assert len(result) == 1

    def test_invalid_regex_rejected(self) -> None:
        """Invalid regex fails at validation."""
        with pytest.raises(ValidationError):
            MentionCountParams(target="[invalid", is_regex=True, min=1)

    def test_bounds_order_validated(self) -> None:
        """Min > max fails validation."""
        with pytest.raises(ValidationError):
            MentionCountParams(target="x", min=5, max=1)

    def test_non_negative_bounds(self) -> None:
        """Negative bounds fail validation."""
        with pytest.raises(ValidationError):
            MentionCountParams(target="x", min=-1)
        with pytest.raises(ValidationError):
            MentionCountParams(target="x", max=-1)

    def test_zero_min_valid(self) -> None:
        """min=0 is valid."""
        params = MentionCountParams(target="x", min=0)
        assert params.min == 0

    def test_multiple_items_concatenated(self) -> None:
        """Multiple items are concatenated with newlines."""
        rule = MentionCountRule()
        params = MentionCountParams(target="Python", min=2)
        resolved: Resolved = _resolved(["I love Python.", "Python is great."])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # Should find 2 mentions of "Python"
        assert result == []

    def test_non_overlapping_regex_matches(self) -> None:
        """Regex uses non-overlapping matches (like findall)."""
        rule = MentionCountRule()
        params = MentionCountParams(target="aa", is_regex=True, min=2)
        resolved: Resolved = _resolved(["aaa"])
        result = rule.check(
            rule_id="test.mention",
            severity=Severity.WARNING,
            resolved=resolved,
            params=params,
        )
        # "aaa" contains only 1 non-overlapping "aa"
        assert len(result) == 1

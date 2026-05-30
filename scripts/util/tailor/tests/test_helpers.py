"""Tests for tailor.lint.content.rules._helpers module.

Tests cover text tokenization, sentence splitting, syllable counting,
string filtering, and substantive word counting.
"""

from __future__ import annotations

from tailor.lint.content.rules._helpers import (
    STOPWORDS,
    as_strings,
    count_substantive_words,
    count_syllables,
    split_sentences,
    tokenize,
)


class TestStopwords:
    """Tests for the STOPWORDS frozenset."""

    def test_stopwords_is_frozenset(self) -> None:
        """STOPWORDS is an immutable frozenset."""
        assert isinstance(STOPWORDS, frozenset)

    def test_stopwords_contains_common_articles(self) -> None:
        """STOPWORDS includes articles a, an, the."""
        assert "a" in STOPWORDS
        assert "an" in STOPWORDS
        assert "the" in STOPWORDS

    def test_stopwords_contains_common_prepositions(self) -> None:
        """STOPWORDS includes common prepositions."""
        assert "in" in STOPWORDS
        assert "on" in STOPWORDS
        assert "at" in STOPWORDS
        assert "to" in STOPWORDS
        assert "for" in STOPWORDS
        assert "of" in STOPWORDS
        assert "with" in STOPWORDS
        assert "by" in STOPWORDS
        assert "from" in STOPWORDS

    def test_stopwords_contains_common_conjunctions(self) -> None:
        """STOPWORDS includes conjunctions and, or, but."""
        assert "and" in STOPWORDS
        assert "or" in STOPWORDS
        assert "but" in STOPWORDS

    def test_stopwords_contains_auxiliary_verbs(self) -> None:
        """STOPWORDS includes auxiliary verbs."""
        assert "is" in STOPWORDS
        assert "are" in STOPWORDS
        assert "was" in STOPWORDS
        assert "were" in STOPWORDS
        assert "be" in STOPWORDS
        assert "been" in STOPWORDS
        assert "has" in STOPWORDS
        assert "have" in STOPWORDS
        assert "had" in STOPWORDS

    def test_stopwords_contains_pronouns(self) -> None:
        """STOPWORDS includes pronouns."""
        assert "i" in STOPWORDS
        assert "you" in STOPWORDS
        assert "he" in STOPWORDS
        assert "she" in STOPWORDS
        assert "it" in STOPWORDS
        assert "we" in STOPWORDS
        assert "they" in STOPWORDS

    def test_stopwords_has_sufficient_size(self) -> None:
        """STOPWORDS contains at least 15 common words (sanity check)."""
        assert len(STOPWORDS) >= 15


class TestTokenize:
    """Tests for the tokenize function."""

    def test_tokenize_empty_string(self) -> None:
        """Empty string returns empty list."""
        assert tokenize("") == []

    def test_tokenize_whitespace_only(self) -> None:
        """Whitespace-only string returns empty list."""
        assert tokenize("   \t\n  ") == []

    def test_tokenize_simple_words(self) -> None:
        """Simple words are extracted in order."""
        assert tokenize("hello world") == ["hello", "world"]

    def test_tokenize_preserves_case(self) -> None:
        """Tokenize preserves case sensitivity."""
        assert tokenize("Hello WORLD") == ["Hello", "WORLD"]

    def test_tokenize_preserves_internal_apostrophes(self) -> None:
        """Internal apostrophes (contractions) are preserved."""
        assert tokenize("don't can't it's") == ["don't", "can't", "it's"]

    def test_tokenize_removes_external_punctuation(self) -> None:
        """Leading/trailing punctuation is removed; words are extracted."""
        result = tokenize("Hello, world! (test) [more].")
        assert "Hello" in result
        assert "world" in result
        assert "test" in result
        assert "more" in result

    def test_tokenize_excludes_pure_digits(self) -> None:
        """Pure numeric strings are excluded."""
        result = tokenize("hello 123 world 456")
        assert result == ["hello", "world"]

    def test_tokenize_excludes_punctuation_only(self) -> None:
        """Punctuation-only tokens are excluded."""
        result = tokenize("hello ... world !!! test")
        assert result == ["hello", "world", "test"]

    def test_tokenize_multiline(self) -> None:
        """Words across multiple lines are extracted."""
        text = "hello\nworld\ntest"
        assert tokenize(text) == ["hello", "world", "test"]

    def test_tokenize_mixed_punctuation(self) -> None:
        """Mixed punctuation is handled correctly."""
        text = 'it\'s the "best"-practice option'
        result = tokenize(text)
        assert "it's" in result
        assert "best" in result
        assert "practice" in result
        assert "option" in result


class TestSplitSentences:
    """Tests for the split_sentences function."""

    def test_split_sentences_empty_string(self) -> None:
        """Empty string returns empty list."""
        assert split_sentences("") == []

    def test_split_sentences_whitespace_only(self) -> None:
        """Whitespace-only string returns empty list."""
        assert split_sentences("   \n  ") == []

    def test_split_sentences_no_period(self) -> None:
        """Single sentence without terminal punctuation is returned."""
        assert split_sentences("Hello world") == ["Hello world"]

    def test_split_sentences_period(self) -> None:
        """Sentence ending in period is extracted (punctuation preserved)."""
        assert split_sentences("Hello world.") == ["Hello world."]

    def test_split_sentences_multiple_periods(self) -> None:
        """Multiple sentences separated by periods are split (punctuation preserved)."""
        result = split_sentences("One. Two. Three.")
        assert result == ["One.", "Two.", "Three."]

    def test_split_sentences_question_mark(self) -> None:
        """Sentences ending in ? are split correctly (punctuation preserved)."""
        result = split_sentences("What? Answer.")
        assert result == ["What?", "Answer."]

    def test_split_sentences_exclamation_mark(self) -> None:
        """Sentences ending in ! are split correctly (punctuation preserved)."""
        result = split_sentences("Great! Excellent!")
        assert result == ["Great!", "Excellent!"]

    def test_split_sentences_mixed_punctuation(self) -> None:
        """Mixed end punctuation (?!.) is handled (punctuation preserved)."""
        result = split_sentences("Who? That! This.")
        assert len(result) == 3
        assert result == ["Who?", "That!", "This."]

    def test_split_sentences_newlines_split(self) -> None:
        """Newlines act as sentence boundaries."""
        result = split_sentences("First\nSecond\nThird")
        assert result == ["First", "Second", "Third"]

    def test_split_sentences_multiple_newlines(self) -> None:
        """Multiple newlines are treated as a single boundary."""
        result = split_sentences("One.\n\nTwo.")
        assert len(result) == 2

    def test_split_sentences_trailing_whitespace_stripped(self) -> None:
        """Trailing whitespace is stripped from each sentence (punctuation preserved)."""
        result = split_sentences("  One.   Two.  ")
        assert result == ["One.", "Two."]

    def test_split_sentences_with_bullet_item_format(self) -> None:
        """Bullet item format (newline without period) is handled."""
        text = "Led team\nDesigned system\nBuilt feature"
        result = split_sentences(text)
        assert result == ["Led team", "Designed system", "Built feature"]


class TestCountSyllables:
    """Tests for the count_syllables function."""

    def test_count_syllables_empty_string(self) -> None:
        """Empty string returns 0."""
        assert count_syllables("") == 0

    def test_count_syllables_whitespace_only(self) -> None:
        """Whitespace-only string returns 0."""
        assert count_syllables("   ") == 0

    def test_count_syllables_single_vowel_group(self) -> None:
        """Single vowel group counts as 1."""
        assert count_syllables("cat") == 1
        assert count_syllables("bat") == 1
        assert count_syllables("the") == 1

    def test_count_syllables_multiple_vowel_groups(self) -> None:
        """Multiple vowel groups counted correctly."""
        assert count_syllables("hello") == 2
        assert count_syllables("apple") == 2
        assert count_syllables("water") == 2

    def test_count_syllables_silent_e_rule(self) -> None:
        """Silent e rule: final e is dropped if count > 1."""
        assert count_syllables("made") == 1  # ma-de, but silent e drops it
        assert count_syllables("make") == 1  # ma-ke, but silent e drops it
        assert count_syllables("bake") == 1  # ba-ke, but silent e drops it

    def test_count_syllables_pronounced_final_e_endings(self) -> None:
        """Words ending in le, ee, ye, oe, ae, ie, ue keep the final e."""
        assert count_syllables("table") == 2  # ta-ble
        assert count_syllables("tree") == 1  # tree has only one vowel group
        assert count_syllables("canoe") == 2  # ca-noe

    def test_count_syllables_y_as_vowel(self) -> None:
        """Y is counted as a vowel."""
        assert count_syllables("happy") == 2  # hap-py
        assert count_syllables("rhythm") == 1  # rhythm (single y group)

    def test_count_syllables_punctuation_stripped(self) -> None:
        """Surrounding punctuation is stripped before counting."""
        assert count_syllables("'hello'") == 2
        assert count_syllables('"apple"') == 2
        assert count_syllables("(cat)") == 1

    def test_count_syllables_case_insensitive(self) -> None:
        """Case doesn't affect syllable count."""
        assert count_syllables("Hello") == count_syllables("hello")
        assert count_syllables("APPLE") == count_syllables("apple")

    def test_count_syllables_minimum_one_for_any_letters(self) -> None:
        """Any word with letters returns at least 1."""
        assert count_syllables("a") == 1
        assert count_syllables("I") == 1
        assert count_syllables("y") == 1

    def test_count_syllables_complex_words(self) -> None:
        """Complex real-world examples."""
        assert count_syllables("beautiful") >= 3
        assert count_syllables("engineering") >= 3
        assert count_syllables("system") == 2


class TestAsStrings:
    """Tests for the as_strings function."""

    def test_as_strings_empty_list(self) -> None:
        """Empty list returns empty list."""
        assert as_strings([]) == []

    def test_as_strings_only_strings(self) -> None:
        """All strings are preserved in order."""
        items: list[object] = ["hello", "world", "test"]
        result = as_strings(items)
        assert result == ["hello", "world", "test"]

    def test_as_strings_filters_non_strings(self) -> None:
        """Non-string items are filtered out."""
        items: list[object] = ["hello", 123, "world", None, {}]
        result = as_strings(items)
        assert result == ["hello", "world"]

    def test_as_strings_filters_dicts(self) -> None:
        """Dictionaries are filtered out."""
        items: list[object] = ["text", {"key": "value"}]
        assert as_strings(items) == ["text"]

    def test_as_strings_filters_lists(self) -> None:
        """Lists are filtered out."""
        items: list[object] = ["text", [1, 2, 3]]
        assert as_strings(items) == ["text"]

    def test_as_strings_preserves_order(self) -> None:
        """Order of string items is preserved."""
        items: list[object] = [1, "a", None, "b", {}, "c"]
        assert as_strings(items) == ["a", "b", "c"]

    def test_as_strings_empty_strings_included(self) -> None:
        """Empty strings are included (they are still strings)."""
        items: list[object] = ["hello", "", "world"]
        assert as_strings(items) == ["hello", "", "world"]


class TestCountSubstantiveWords:
    """Tests for the count_substantive_words function."""

    def test_count_substantive_words_empty_string(self) -> None:
        """Empty string has 0 substantive words."""
        assert count_substantive_words("") == 0

    def test_count_substantive_words_all_stopwords(self) -> None:
        """All stopwords results in 0 count."""
        assert count_substantive_words("the a an and or but in on at") == 0

    def test_count_substantive_words_filters_stopwords(self) -> None:
        """Stopwords are excluded from count."""
        result = count_substantive_words("the cat sat on the mat")
        # "cat", "sat", "mat" are substantive; "the", "on" are stopwords
        assert result == 3

    def test_count_substantive_words_case_insensitive(self) -> None:
        """Stopword matching is case-insensitive."""
        result = count_substantive_words("The CAT sat ON the MAT")
        assert result == 3

    def test_count_substantive_words_all_substantive(self) -> None:
        """Non-stopword tokens are all counted."""
        assert count_substantive_words("cat dog fish") == 3
        assert count_substantive_words("hello world python") == 3

    def test_count_substantive_words_mixed(self) -> None:
        """Mix of stopwords and substantive words."""
        result = count_substantive_words("I went to the store and bought milk")
        # "went", "store", "bought", "milk" are substantive (4)
        # "I", "to", "the", "and" are stopwords
        assert result == 4

    def test_count_substantive_words_custom_stopwords(self) -> None:
        """Custom stopword set can be provided."""
        custom_stopwords = frozenset({"custom", "words"})
        result = count_substantive_words("hello custom words world", stopwords=custom_stopwords)
        # Only "custom" and "words" are filtered
        assert result == 2

    def test_count_substantive_words_punctuation_stripped(self) -> None:
        """Punctuation doesn't affect word tokenization."""
        result = count_substantive_words("hello, world! test.")
        assert result == 3

    def test_count_substantive_words_single_substantive(self) -> None:
        """Single substantive word surrounded by stopwords."""
        result = count_substantive_words("the cat")
        assert result == 1

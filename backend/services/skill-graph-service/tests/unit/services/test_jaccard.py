"""Unit tests for Jaccard similarity matching."""

from __future__ import annotations

import pytest
from skill_graph_service.services.jaccard import (
    extract_ngrams,
    find_best_jaccard_match,
    is_high_jaccard_match,
    jaccard_ngram_similarity,
)


class TestExtractNgrams:
    """Tests for extract_ngrams function."""

    def test_extracts_trigrams_by_default(self) -> None:
        """Test default trigram extraction."""
        result = extract_ngrams("python")
        # pyt, yth, tho, hon
        assert result == frozenset({"pyt", "yth", "tho", "hon"})

    def test_handles_case_and_whitespace(self) -> None:
        """Test normalization during extraction."""
        result = extract_ngrams("  PyThOn  ")
        assert result == frozenset({"pyt", "yth", "tho", "hon"})

    def test_returns_empty_for_short_text(self) -> None:
        """Test handling of text shorter than n."""
        assert extract_ngrams("py", n=3) == frozenset()

    def test_custom_ngram_size(self) -> None:
        """Test extraction with custom n."""
        result = extract_ngrams("python", n=2)
        # py, yt, th, ho, on
        assert result == frozenset({"py", "yt", "th", "ho", "on"})


class TestJaccardNgramSimilarity:
    """Tests for jaccard_ngram_similarity function."""

    def test_identical_strings(self) -> None:
        """Test similarity of identical strings."""
        assert jaccard_ngram_similarity("python", "python") == pytest.approx(1.0)

    def test_completely_different_strings(self) -> None:
        """Test similarity of strings with no overlapping n-grams."""
        assert jaccard_ngram_similarity("abc", "xyz") == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        """Test similarity of strings with partial overlap.

        "python" trigrams: {pyt, yth, tho, hon} (4)
        "pyth" trigrams: {pyt, yth} (2)
        Intersection size 2, union size 4 => 2/4 = 0.5
        """
        assert jaccard_ngram_similarity("python", "pyth") == pytest.approx(0.5)

    def test_handles_empty_ngrams(self) -> None:
        """Test handling when one string produces no n-grams."""
        assert jaccard_ngram_similarity("py", "python") == pytest.approx(0.0)


class TestIsHighJaccardMatch:
    """Tests for is_high_jaccard_match function."""

    def test_high_similarity(self) -> None:
        """Test strings with similarity >= 0.9."""
        assert is_high_jaccard_match("kubernetes", "kubernetes") is True
        assert is_high_jaccard_match("python programming", "python programmin") is True

    def test_low_similarity(self) -> None:
        """Test strings with similarity < 0.9."""
        assert is_high_jaccard_match("python", "java") is False


class TestFindBestJaccardMatch:
    """Tests for find_best_jaccard_match function."""

    def test_finds_best_match(self) -> None:
        """Test finding the best match among candidates."""
        candidates = [
            ("1", "java"),
            ("2", "python"),
            ("3", "pyth"),
        ]
        result = find_best_jaccard_match("python", candidates)
        assert result is not None
        assert result[0] == "2"
        assert result[1] == "python"
        assert result[2] == pytest.approx(1.0)

    def test_respects_threshold(self) -> None:
        """Test that matches below threshold are ignored."""
        candidates = [("1", "java")]
        result = find_best_jaccard_match("python", candidates, threshold=0.9)
        assert result is None

    def test_returns_none_for_empty_candidates(self) -> None:
        """Test handling of empty candidate list."""
        assert find_best_jaccard_match("python", []) is None

"""Jaccard n-gram similarity for skill matching."""

from __future__ import annotations

from typing import Final

_DEFAULT_NGRAM_SIZE: Final[int] = 3
_HIGH_SIMILARITY_THRESHOLD: Final[float] = 0.90


def extract_ngrams(text: str, n: int = _DEFAULT_NGRAM_SIZE) -> frozenset[str]:
    """Extract character n-grams from normalized text.

    Time complexity: O(len(text))
    Space complexity: O(len(text))

    Args:
        text: Input string to extract n-grams from
        n: Size of character n-grams (default: 3)

    Returns:
        Frozenset of n-gram strings

    """
    normalized = text.lower().strip()
    if len(normalized) < n:
        return frozenset()
    return frozenset(normalized[i : i + n] for i in range(len(normalized) - n + 1))


def jaccard_ngram_similarity(
    s1: str,
    s2: str,
    *,
    n: int = _DEFAULT_NGRAM_SIZE,
) -> float:
    """Compute character n-gram Jaccard similarity between two strings.

    Jaccard similarity = |A intersection B| / |A union B|

    This is effective for catching abbreviations and typos that semantic
    similarity misses (e.g., "k8s" vs "kubernetes").

    Time complexity: O(len(s1) + len(s2))
    Space complexity: O(len(s1) + len(s2))

    Args:
        s1: First string to compare
        s2: Second string to compare
        n: Size of character n-grams (default: 3)

    Returns:
        Jaccard similarity coefficient in [0.0, 1.0]

    """
    ng1 = extract_ngrams(s1, n)
    ng2 = extract_ngrams(s2, n)

    if not ng1 or not ng2:
        return 0.0

    intersection_size = len(ng1 & ng2)
    union_size = len(ng1 | ng2)

    return intersection_size / union_size


def is_high_jaccard_match(s1: str, s2: str) -> bool:
    """Check if two strings have high Jaccard similarity (≥0.90).

    Args:
        s1: First string
        s2: Second string

    Returns:
        True if similarity >= 0.90

    """
    return jaccard_ngram_similarity(s1, s2) >= _HIGH_SIMILARITY_THRESHOLD


def find_best_jaccard_match(
    query: str,
    candidates: list[tuple[str, str]],
    *,
    threshold: float = _HIGH_SIMILARITY_THRESHOLD,
) -> tuple[str, str, float] | None:
    """Find the best Jaccard match from a list of candidates.

    Args:
        query: The query string to match
        candidates: List of (id, name) tuples to search
        threshold: Minimum similarity threshold (default: 0.90)

    Returns:
        Tuple of (id, name, similarity) for best match, or None if no match

    """
    best_match: tuple[str, str, float] | None = None
    best_score = threshold

    for candidate_id, candidate_name in candidates:
        score = jaccard_ngram_similarity(query, candidate_name)
        if score >= best_score:
            best_score = score
            best_match = (candidate_id, candidate_name, score)

    return best_match

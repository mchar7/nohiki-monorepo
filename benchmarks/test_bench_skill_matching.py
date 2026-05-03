"""Benchmarks for skill matching algorithms (skill-graph-service).

Measures Jaccard n-gram similarity computation, n-gram extraction,
best-match search, and result construction -- the pure CPU operations
in the skill normalization pipeline.

Functions inlined from skill_graph_service.services.jaccard to avoid
importing the service package (not on sys.path for benchmarks).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

import pytest

# Inlined from skill_graph_service.services.jaccard (pure functions)

_DEFAULT_NGRAM_SIZE: Final[int] = 3
_HIGH_SIMILARITY_THRESHOLD: Final[float] = 0.90


def extract_ngrams(text: str, n: int = _DEFAULT_NGRAM_SIZE) -> frozenset[str]:
    """Extract character n-grams from normalized text."""
    normalized = text.lower().strip()
    if len(normalized) < n:
        return frozenset()
    return frozenset(normalized[i : i + n] for i in range(len(normalized) - n + 1))


def jaccard_ngram_similarity(s1: str, s2: str, *, n: int = _DEFAULT_NGRAM_SIZE) -> float:
    """Compute character n-gram Jaccard similarity between two strings."""
    ng1 = extract_ngrams(s1, n)
    ng2 = extract_ngrams(s2, n)
    if not ng1 or not ng2:
        return 0.0
    intersection_size = len(ng1 & ng2)
    union_size = len(ng1 | ng2)
    return intersection_size / union_size


def is_high_jaccard_match(s1: str, s2: str) -> bool:
    """Check if two strings have high Jaccard similarity (≥0.90)."""
    return jaccard_ngram_similarity(s1, s2) >= _HIGH_SIMILARITY_THRESHOLD


def find_best_jaccard_match(
    query: str,
    candidates: list[tuple[str, str]],
    *,
    threshold: float = _HIGH_SIMILARITY_THRESHOLD,
) -> tuple[str, str, float] | None:
    """Find the best Jaccard match from a list of candidates."""
    best_match: tuple[str, str, float] | None = None
    best_score = threshold
    for candidate_id, candidate_name in candidates:
        score = jaccard_ngram_similarity(query, candidate_name)
        if score >= best_score:
            best_score = score
            best_match = (candidate_id, candidate_name, score)
    return best_match


# N-gram extraction (first step of every Jaccard comparison)


def test_bench_extract_ngrams_short(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark n-gram extraction for short skill name (5 chars)."""
    benchmark(extract_ngrams, "react")


def test_bench_extract_ngrams_medium(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark n-gram extraction for medium skill name (10 chars)."""
    benchmark(extract_ngrams, "kubernetes")


def test_bench_extract_ngrams_long(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark n-gram extraction for long skill name (30+ chars)."""
    benchmark(extract_ngrams, "amazon web services cloud formation")


def test_bench_extract_ngrams_too_short(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark n-gram extraction for sub-n-gram-size input (fast path)."""
    benchmark(extract_ngrams, "go")


# Pairwise Jaccard similarity (core of matching)


def test_bench_jaccard_identical(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark Jaccard similarity for identical strings (upper bound)."""
    benchmark(jaccard_ngram_similarity, "python", "python")


def test_bench_jaccard_similar(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark Jaccard for similar strings (abbreviation case)."""
    benchmark(jaccard_ngram_similarity, "kubernetes", "k8s")


def test_bench_jaccard_close_match(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark Jaccard for close match (typo detection)."""
    benchmark(jaccard_ngram_similarity, "javascript", "javascrip")


def test_bench_jaccard_different(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark Jaccard for completely different strings."""
    benchmark(jaccard_ngram_similarity, "python", "kubernetes")


def test_bench_jaccard_long_strings(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark Jaccard for long multi-word skill names."""
    benchmark(
        jaccard_ngram_similarity,
        "amazon web services cloud formation",
        "aws cloudformation infrastructure",
    )


def test_bench_is_high_jaccard_match(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark high-match threshold check (≥0.90)."""
    benchmark(is_high_jaccard_match, "react.js", "reactjs")


# Best-match search (scans candidate list)

_SKILL_CANDIDATES_10: list[tuple[str, str]] = [
    ("1", "python"),
    ("2", "javascript"),
    ("3", "typescript"),
    ("4", "react"),
    ("5", "kubernetes"),
    ("6", "docker"),
    ("7", "aws"),
    ("8", "postgresql"),
    ("9", "redis"),
    ("10", "kafka"),
]

_SKILL_CANDIDATES_100: list[tuple[str, str]] = [(str(i), f"skill-{i}-{'a' * (i % 10 + 3)}") for i in range(100)]

_SKILL_CANDIDATES_500: list[tuple[str, str]] = [(str(i), f"skill-{i}-{'b' * (i % 15 + 3)}") for i in range(500)]


def test_bench_find_best_match_10(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark best-match search over 10 candidates."""
    benchmark(find_best_jaccard_match, "pythn", _SKILL_CANDIDATES_10)


def test_bench_find_best_match_100(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark best-match search over 100 candidates."""
    benchmark(find_best_jaccard_match, "pythn", _SKILL_CANDIDATES_100)


def test_bench_find_best_match_500(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark best-match search over 500 candidates (max_jaccard_candidates)."""
    benchmark(find_best_jaccard_match, "pythn", _SKILL_CANDIDATES_500)


def test_bench_find_best_match_hit(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark best-match search with actual match found."""
    benchmark(find_best_jaccard_match, "python", _SKILL_CANDIDATES_10)


def test_bench_find_best_match_no_hit(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark best-match search with no match (full scan, no early exit)."""
    benchmark(find_best_jaccard_match, "zzzzzzzzz", _SKILL_CANDIDATES_10)


# Normalization result construction (inlined -- avoids DB imports)

_SAMPLE_UUID = UUID("550e8400-e29b-41d4-a716-446655440000")


def _build_result_dict(
    canonical_id: UUID | None,
    canonical_name: str | None,
    match_type: str,
    confidence: str,
    similarity_score: float,
) -> dict[str, object]:
    """Inline result builder matching SkillNormalizationResult fields."""
    return {
        "canonical_id": canonical_id,
        "canonical_name": canonical_name,
        "match_type": match_type,
        "confidence": confidence,
        "similarity_score": similarity_score,
    }


def test_bench_build_exact_result(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building an exact match result."""
    benchmark(_build_result_dict, _SAMPLE_UUID, "python", "EXACT", "CONFIDENT", 1.0)


def test_bench_build_no_match_result(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a no-match result."""
    benchmark(_build_result_dict, None, None, "NEW", "NO_MATCH", 0.0)

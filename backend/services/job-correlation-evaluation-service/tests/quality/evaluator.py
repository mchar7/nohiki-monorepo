"""Pure validation and information-retrieval metrics for the ranking quality gate."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite, log2
from pathlib import Path

EXPECTED_COUNT = 48
MIN_RELEVANT = 5
MIN_NEGATIVE = 5


class QualityFixtureError(ValueError):
    """Raised when the immutable quality corpus is malformed."""


@dataclass(frozen=True, slots=True)
class RankedItem:
    fixture_id: str
    title: str
    grade: int
    score: int
    ranking_index: float


def load_fixture(path: Path) -> dict[str, object]:
    fixture = json.loads(path.read_text())
    candidates = fixture.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != EXPECTED_COUNT:
        error_message = f"fixture must contain exactly {EXPECTED_COUNT} candidates"
        raise QualityFixtureError(error_message)
    ids = [candidate.get("fixture_id") for candidate in candidates]
    if len(set(ids)) != EXPECTED_COUNT or any(not isinstance(value, str) for value in ids):
        error_message = "fixture candidate IDs must be unique strings"
        raise QualityFixtureError(error_message)
    grades = [candidate.get("judgment", {}).get("grade") for candidate in candidates]
    if any(type(grade) is not int or not 0 <= grade <= 3 for grade in grades):
        error_message = "every candidate must have an integer grade in 0..3"
        raise QualityFixtureError(error_message)
    if sum(grade >= 2 for grade in grades) < MIN_RELEVANT or grades.count(0) < MIN_NEGATIVE:
        error_message = "fixture lacks required positive or negative grade support"
        raise QualityFixtureError(error_message)
    semantic = [candidate.get("semantic_score") for candidate in candidates]
    semantic_status = fixture.get("provenance", {}).get("semantic_inputs_status")
    if semantic_status == "ready":
        if any(type(value) not in (int, float) or not isfinite(value) for value in semantic):
            error_message = "ready semantic inputs must all be finite"
            raise QualityFixtureError(error_message)
    elif any(value is not None for value in semantic):
        error_message = "pending semantic inputs must all be null"
        raise QualityFixtureError(error_message)
    ranking_inputs = {
        "profile": fixture["profile"],
        "candidates": [
            {key: value for key, value in candidate.items() if key not in ("description", "judgment")}
            for candidate in candidates
        ],
    }
    actual = sha256(
        json.dumps(ranking_inputs, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    expected = fixture.get("provenance", {}).get("ranking_inputs_sha256")
    if actual != expected:
        error_message = f"ranking input checksum mismatch: expected {expected}, got {actual}"
        raise QualityFixtureError(error_message)
    return fixture


def ndcg(grades: list[int], k: int) -> float:
    def dcg(values: list[int]) -> float:
        return sum((2**grade - 1) / log2(rank + 2) for rank, grade in enumerate(values[:k]))

    ideal = dcg(sorted(grades, reverse=True))
    return dcg(grades) / ideal if ideal else 0.0


def reciprocal_rank(grades: list[int], relevant_grade: int = 3) -> float:
    return next((1.0 / rank for rank, grade in enumerate(grades, 1) if grade >= relevant_grade), 0.0)


def precision_at(grades: list[int], k: int, relevant_grade: int = 2) -> float:
    return sum(grade >= relevant_grade for grade in grades[:k]) / k


def percentile_nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * percentile + 0.999999999))
    return ordered[min(rank, len(ordered)) - 1]


def evaluate(items: list[RankedItem], sentinel_id: str = "DA-11") -> dict[str, object]:
    if len(items) != EXPECTED_COUNT or len({item.fixture_id for item in items}) != EXPECTED_COUNT:
        error_message = "ranking must contain each of the 48 fixture candidates exactly once"
        raise QualityFixtureError(error_message)
    grades = [item.grade for item in items]
    scores = [item.score for item in items]
    histogram = Counter(scores)
    grade3_positions = [index for index, grade in enumerate(grades) if grade == 3]
    grade0_positions = [index for index, grade in enumerate(grades) if grade == 0]
    sentinel_rank = next(index for index, item in enumerate(items, 1) if item.fixture_id == sentinel_id)
    relevant_positions = [index for index, grade in enumerate(grades, 1) if grade >= 2]
    metrics = {
        "ndcg_at_5": ndcg(grades, 5),
        "ndcg_at_10": ndcg(grades, 10),
        "grade3_mrr": reciprocal_rank(grades),
        "precision_at_5_grade2": precision_at(grades, 5),
        "grade0_top5": sum(grade == 0 for grade in grades[:5]),
        "grade3_above_grade0": max(grade3_positions) < min(grade0_positions),
        "sentinel_rank": sentinel_rank,
        "sentinel_below_relevant": sentinel_rank > max(relevant_positions),
        "score_range": max(scores) - min(scores),
        "p90_p10": percentile_nearest_rank(scores, 0.9) - percentile_nearest_rank(scores, 0.1),
        "integer_buckets": len(histogram),
        "largest_bucket": max(histogram.values()),
        "best_grade3_grade0_margin": max(item.score for item in items if item.grade == 3)
        - max(item.score for item in items if item.grade == 0),
    }
    violations = []
    floors = {
        "ndcg_at_5": metrics["ndcg_at_5"] >= 0.90,
        "ndcg_at_10": metrics["ndcg_at_10"] >= 0.85,
        "grade3_mrr": metrics["grade3_mrr"] == 1.0,
        "precision_at_5_grade2": metrics["precision_at_5_grade2"] >= 0.80,
        "grade0_top5": metrics["grade0_top5"] == 0,
        "grade3_above_grade0": metrics["grade3_above_grade0"],
        "sentinel_outside_top10": sentinel_rank > 10,
        "sentinel_below_relevant": metrics["sentinel_below_relevant"],
        "score_range": metrics["score_range"] >= 15,
        "p90_p10": metrics["p90_p10"] >= 10,
        "integer_buckets": metrics["integer_buckets"] >= 10,
        "largest_bucket": metrics["largest_bucket"] <= 12,
        "grade3_grade0_margin": metrics["best_grade3_grade0_margin"] >= 10,
    }
    violations.extend(name for name, passed in floors.items() if not passed)
    return {"metrics": metrics, "histogram": dict(sorted(histogram.items(), reverse=True)), "violations": violations}


def failure_diagnostic(items: list[RankedItem], report: dict[str, object]) -> str:
    top = "\n".join(
        f"{rank:2d}. {item.fixture_id} grade={item.grade} score={item.score} "
        f"index={item.ranking_index:.6f} {item.title}"
        for rank, item in enumerate(items[:10], 1)
    )
    return (
        f"violations={report['violations']}\nmetrics={report['metrics']}\n"
        f"histogram={report['histogram']}\ntop10:\n{top}"
    )

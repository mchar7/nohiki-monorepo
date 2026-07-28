"""Core analysis logic for skill semantic similarity."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from skill_semantic_analysis.analysis.test_pairs import SkillPair

MAX_REPORT_BYTES = 10 * 1024 * 1024


@dataclass
class SimilarityResult:
    """Result of similarity computation for a skill pair."""

    skill_a: str
    skill_b: str
    similarity: float
    should_match: bool
    category: str
    notes: str


@dataclass
class ThresholdMetrics:
    """Metrics at a specific threshold."""

    threshold: float
    precision: float
    recall: float
    f1: float
    tp: int
    fn: int
    tn: int
    fp: int


@dataclass
class AnalysisReport:
    """Complete analysis report."""

    total_pairs: int
    true_positive_count: int
    true_negative_count: int
    min_tp_similarity: float
    max_tn_similarity: float
    separation_gap: float
    best_threshold: float
    best_f1: float
    threshold_metrics: list[ThresholdMetrics]
    missed_matches: list[dict]
    false_positives: list[dict]
    edge_cases: list[dict]
    all_results: list[dict] = field(default_factory=list)

    def save(self, path: Path) -> None:
        """Save report to JSON file."""
        data = {
            "summary": {
                "total_pairs": self.total_pairs,
                "true_positive_pairs": self.true_positive_count,
                "true_negative_pairs": self.true_negative_count,
                "min_true_positive_similarity": self.min_tp_similarity,
                "max_true_negative_similarity": self.max_tn_similarity,
                "separation_gap": self.separation_gap,
                "best_threshold": self.best_threshold,
                "best_f1": self.best_f1,
            },
            "threshold_analysis": [
                {
                    "threshold": m.threshold,
                    "precision": m.precision,
                    "recall": m.recall,
                    "f1": m.f1,
                    "tp": m.tp,
                    "fn": m.fn,
                    "tn": m.tn,
                    "fp": m.fp,
                }
                for m in self.threshold_metrics
            ],
            "missed_matches": self.missed_matches,
            "false_positives": self.false_positives,
            "edge_cases": self.edge_cases,
            "all_results_sorted": self.all_results,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary_file:
            json.dump(data, temporary_file, indent=2)
        temporary_path = Path(temporary_file.name)
        try:
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> AnalysisReport:
        """Load and validate a bounded report from a JSON file."""
        if not path.is_file():
            message = f"Report is not a file: {path}"
            raise ValueError(message)
        if path.stat().st_size > MAX_REPORT_BYTES:
            message = f"Report exceeds {MAX_REPORT_BYTES} bytes"
            raise ValueError(message)
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = data["summary"]
        return cls(
            total_pairs=summary["total_pairs"],
            true_positive_count=summary["true_positive_pairs"],
            true_negative_count=summary["true_negative_pairs"],
            min_tp_similarity=summary["min_true_positive_similarity"],
            max_tn_similarity=summary["max_true_negative_similarity"],
            separation_gap=summary["separation_gap"],
            best_threshold=summary["best_threshold"],
            best_f1=summary["best_f1"],
            threshold_metrics=[ThresholdMetrics(**m) for m in data["threshold_analysis"]],
            missed_matches=data.get("missed_matches", []),
            false_positives=data.get("false_positives", []),
            edge_cases=data.get("edge_cases", []),
            all_results=data.get("all_results_sorted", []),
        )


def _compute_similarity(
    model: SentenceTransformer,
    skill_a: str,
    skill_b: str,
    cache: dict[str, np.ndarray],
) -> float:
    """Compute cosine similarity between two skills."""
    key_a = skill_a.lower()
    key_b = skill_b.lower()

    if key_a not in cache:
        cache[key_a] = np.asarray(model.encode(key_a, normalize_embeddings=True))
    if key_b not in cache:
        cache[key_b] = np.asarray(model.encode(key_b, normalize_embeddings=True))

    return float(np.dot(cache[key_a], cache[key_b]))


def _find_best_threshold(
    results: list[SimilarityResult],
) -> tuple[float, float, list[ThresholdMetrics]]:
    """Find optimal threshold via F1 score optimization."""
    true_positives = [r for r in results if r.should_match]
    true_negatives = [r for r in results if not r.should_match]

    thresholds = np.arange(0.50, 0.95, 0.01)
    metrics_list: list[ThresholdMetrics] = []
    best_threshold = 0.80
    best_f1 = 0.0

    for threshold in thresholds:
        tp = sum(1 for r in true_positives if r.similarity >= threshold)
        fn = sum(1 for r in true_positives if r.similarity < threshold)
        tn = sum(1 for r in true_negatives if r.similarity < threshold)
        fp = sum(1 for r in true_negatives if r.similarity >= threshold)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics_list.append(
            ThresholdMetrics(
                threshold=float(threshold),
                precision=precision,
                recall=recall,
                f1=f1,
                tp=tp,
                fn=fn,
                tn=tn,
                fp=fp,
            )
        )

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = float(threshold)

    return best_threshold, best_f1, metrics_list


def run_threshold_analysis(
    model_name: str,
    test_pairs: list[SkillPair],
    progress_callback: Callable[[str], None] | None = None,
) -> AnalysisReport:
    """Run full threshold analysis on test pairs."""
    from sentence_transformers import SentenceTransformer

    def update(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    update(f"Loading model: {model_name}...")
    model = SentenceTransformer(model_name)

    cache: dict[str, np.ndarray] = {}
    results: list[SimilarityResult] = []

    update(f"Analyzing {len(test_pairs)} pairs...")
    for i, pair in enumerate(test_pairs):
        similarity = _compute_similarity(model, pair.skill_a, pair.skill_b, cache)
        results.append(
            SimilarityResult(
                skill_a=pair.skill_a,
                skill_b=pair.skill_b,
                similarity=similarity,
                should_match=pair.should_match,
                category=pair.category,
                notes=pair.notes,
            )
        )
        if (i + 1) % 20 == 0:
            update(f"Processed {i + 1}/{len(test_pairs)} pairs...")

    update("Computing optimal threshold...")

    true_positives = [r for r in results if r.should_match]
    true_negatives = [r for r in results if not r.should_match]

    min_tp = min(r.similarity for r in true_positives) if true_positives else 0.0
    max_tn = max(r.similarity for r in true_negatives) if true_negatives else 1.0

    best_threshold, best_f1, metrics = _find_best_threshold(results)

    missed = [
        {"pair": [r.skill_a, r.skill_b], "similarity": r.similarity, "category": r.category}
        for r in true_positives
        if r.similarity < best_threshold
    ]

    fps = [
        {"pair": [r.skill_a, r.skill_b], "similarity": r.similarity, "category": r.category}
        for r in true_negatives
        if r.similarity >= best_threshold
    ]

    edges = [
        {
            "pair": [r.skill_a, r.skill_b],
            "similarity": r.similarity,
            "should_match": r.should_match,
            "would_match": r.similarity >= best_threshold,
        }
        for r in results
        if r.category == "edge"
    ]

    all_sorted = [
        {"pair": [r.skill_a, r.skill_b], "similarity": round(r.similarity, 4), "should_match": r.should_match}
        for r in sorted(results, key=lambda x: x.similarity, reverse=True)
    ]

    update("Analysis complete")

    return AnalysisReport(
        total_pairs=len(test_pairs),
        true_positive_count=len(true_positives),
        true_negative_count=len(true_negatives),
        min_tp_similarity=min_tp,
        max_tn_similarity=max_tn,
        separation_gap=min_tp - max_tn,
        best_threshold=best_threshold,
        best_f1=best_f1,
        threshold_metrics=metrics,
        missed_matches=missed,
        false_positives=fps,
        edge_cases=edges,
        all_results=all_sorted,
    )

"""Similarity analysis for threshold calibration.

Computes Jaccard n-gram similarity for test pairs and analyzes
threshold performance to find optimal values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from calibrate_skill_thresholds.data import TestPair

if TYPE_CHECKING:
    from calibrate_skill_thresholds.data import CalibrationDataset

NGRAM_SIZE = 3


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    """Result of similarity computation for a single pair."""

    pair: TestPair
    jaccard_score: float


@dataclass
class ThresholdAnalysis:
    """Performance metrics at a specific threshold."""

    threshold: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        """Precision: TP / (TP + FP)."""
        total = self.true_positives + self.false_positives
        return self.true_positives / total if total > 0 else 0.0

    @property
    def recall(self) -> float:
        """Recall: TP / (TP + FN)."""
        total = self.true_positives + self.false_negatives
        return self.true_positives / total if total > 0 else 0.0

    @property
    def f1_score(self) -> float:
        """F1 score: harmonic mean of precision and recall."""
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * (self.precision * self.recall) / (self.precision + self.recall)

    @property
    def false_positive_rate(self) -> float:
        """False positive rate: FP / (FP + TN)."""
        total = self.false_positives + self.true_negatives
        return self.false_positives / total if total > 0 else 0.0


@dataclass
class DistributionStats:
    """Statistical summary of a score distribution."""

    count: int
    min_val: float
    max_val: float
    mean: float
    median: float
    std: float
    p25: float
    p75: float
    p90: float
    p95: float
    p99: float

    @classmethod
    def from_scores(cls, scores: list[float]) -> DistributionStats:
        """Compute statistics from a list of scores."""
        if not scores:
            return cls(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        arr = np.array(scores)
        return cls(
            count=len(scores),
            min_val=float(np.min(arr)),
            max_val=float(np.max(arr)),
            mean=float(np.mean(arr)),
            median=float(np.median(arr)),
            std=float(np.std(arr)),
            p25=float(np.percentile(arr, 25)),
            p75=float(np.percentile(arr, 75)),
            p90=float(np.percentile(arr, 90)),
            p95=float(np.percentile(arr, 95)),
            p99=float(np.percentile(arr, 99)),
        )


@dataclass
class AnalysisResults:
    """Complete results of similarity analysis."""

    synonym_scores: list[float] = field(default_factory=list)
    distinct_scores: list[float] = field(default_factory=list)
    all_results: list[SimilarityResult] = field(default_factory=list)

    @property
    def synonym_stats(self) -> DistributionStats:
        """Statistics for true synonym scores."""
        return DistributionStats.from_scores(self.synonym_scores)

    @property
    def distinct_stats(self) -> DistributionStats:
        """Statistics for distinct-but-similar scores."""
        return DistributionStats.from_scores(self.distinct_scores)


@dataclass
class CalibrationReport:
    """Complete calibration report with recommendations."""

    results: AnalysisResults
    zero_fp_threshold: float
    threshold_analyses: list[ThresholdAnalysis]
    false_positive_examples: list[dict[str, object]]
    false_negative_examples: list[dict[str, object]]


class JaccardAnalyzer:
    """Computes and analyzes Jaccard n-gram similarity."""

    def __init__(self, ngram_size: int = NGRAM_SIZE) -> None:
        """Initialize analyzer with n-gram size."""
        self.ngram_size = ngram_size

    def compute_similarity(self, text_a: str, text_b: str) -> float:
        """Compute Jaccard similarity using character n-grams."""
        ngrams_a = self._extract_ngrams(text_a)
        ngrams_b = self._extract_ngrams(text_b)

        if not ngrams_a or not ngrams_b:
            return 0.0

        intersection = len(ngrams_a & ngrams_b)
        union = len(ngrams_a | ngrams_b)

        return intersection / union if union > 0 else 0.0

    def _extract_ngrams(self, text: str) -> frozenset[str]:
        """Extract character n-grams from text."""
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9]", "", text)

        if len(text) < self.ngram_size:
            return frozenset()

        return frozenset(text[i : i + self.ngram_size] for i in range(len(text) - self.ngram_size + 1))

    def analyze_dataset(self, dataset: CalibrationDataset) -> AnalysisResults:
        """Compute similarities for all pairs in dataset."""
        results = AnalysisResults()

        for pair in dataset.true_synonyms:
            score = self.compute_similarity(pair.skill_a, pair.skill_b)
            results.synonym_scores.append(score)
            results.all_results.append(SimilarityResult(pair=pair, jaccard_score=score))

        for pair in dataset.distinct_similar:
            score = self.compute_similarity(pair.skill_a, pair.skill_b)
            results.distinct_scores.append(score)
            results.all_results.append(SimilarityResult(pair=pair, jaccard_score=score))

        return results

    def analyze_threshold(self, results: AnalysisResults, threshold: float) -> ThresholdAnalysis:
        """Analyze performance at a specific threshold."""
        tp = sum(1 for s in results.synonym_scores if s >= threshold)
        fn = sum(1 for s in results.synonym_scores if s < threshold)
        fp = sum(1 for s in results.distinct_scores if s >= threshold)
        tn = sum(1 for s in results.distinct_scores if s < threshold)

        return ThresholdAnalysis(
            threshold=threshold,
            true_positives=tp,
            false_positives=fp,
            true_negatives=tn,
            false_negatives=fn,
        )

    def find_zero_fp_threshold(self, results: AnalysisResults) -> float:
        """Find minimum threshold that gives zero false positives."""
        if not results.distinct_scores:
            return 0.0

        max_distinct = max(results.distinct_scores)
        return min(max_distinct + 0.001, 1.0)

    def get_false_positive_examples(
        self,
        results: AnalysisResults,
        threshold: float,
        max_examples: int = 50,
    ) -> list[dict[str, object]]:
        """Get examples of false positives at a threshold."""
        from calibrate_skill_thresholds.data import PairType

        examples: list[dict[str, object]] = []

        for result in results.all_results:
            if result.pair.pair_type == PairType.DISTINCT_SIMILAR and result.jaccard_score >= threshold:
                examples.append(
                    {
                        "skill_a": result.pair.skill_a,
                        "skill_b": result.pair.skill_b,
                        "score": round(result.jaccard_score, 4),
                    },
                )
                if len(examples) >= max_examples:
                    break

        return sorted(examples, key=lambda x: float(x["score"]), reverse=True)

    def get_false_negative_examples(
        self,
        results: AnalysisResults,
        threshold: float,
        max_examples: int = 50,
    ) -> list[dict[str, object]]:
        """Get examples of false negatives at a threshold."""
        from calibrate_skill_thresholds.data import PairType

        examples: list[dict[str, object]] = []

        for result in results.all_results:
            if (
                result.pair.pair_type == PairType.TRUE_SYNONYM
                and result.jaccard_score < threshold
                and result.jaccard_score >= threshold - 0.1
            ):
                examples.append(
                    {
                        "skill_a": result.pair.skill_a,
                        "skill_b": result.pair.skill_b,
                        "score": round(result.jaccard_score, 4),
                    },
                )
                if len(examples) >= max_examples:
                    break

        return sorted(examples, key=lambda x: float(x["score"]), reverse=True)

    def generate_report(
        self,
        results: AnalysisResults,
        thresholds: list[float] | None = None,
    ) -> CalibrationReport:
        """Generate a complete calibration report."""
        if thresholds is None:
            thresholds = [0.80, 0.85, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99]

        zero_fp = self.find_zero_fp_threshold(results)
        analyses = [self.analyze_threshold(results, t) for t in thresholds]
        fp_examples = self.get_false_positive_examples(results, 0.90)
        fn_examples = self.get_false_negative_examples(results, zero_fp)

        return CalibrationReport(
            results=results,
            zero_fp_threshold=zero_fp,
            threshold_analyses=analyses,
            false_positive_examples=fp_examples,
            false_negative_examples=fn_examples,
        )

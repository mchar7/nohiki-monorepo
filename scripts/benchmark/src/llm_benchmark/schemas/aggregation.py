"""Score aggregation and model classification from pointwise judge evaluations.

Aggregates per-model pointwise judge scores into overall model rankings and
classifies each model into tiers based on average scores. Also provides
multi-judge consensus computation and the ``EvaluationResult`` container
returned by the judge engine.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import mean, stdev

from pydantic import BaseModel

from llm_benchmark.config.constants import CAUTION_THRESHOLD, FAIL_THRESHOLD, WARNING_THRESHOLD
from llm_benchmark.schemas.judge import CATEGORY_NAMES, PointwiseJudgment


class Classification(StrEnum):
    """Model classification tier based on evaluation results."""

    PASSED = "PASSED"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    FAIL = "FAIL"


class CategoryAggregate(BaseModel):
    """Aggregated statistics for a single scoring category.

    Attributes:
        category: Category name.
        mean_score: Average score across all evaluated runs.
        stdev_score: Standard deviation of scores (0.0 if fewer than 2 samples).
        min_score: Lowest score observed.
        max_score: Highest score observed.
        sample_count: Number of evaluated runs contributing to this aggregate.
    """

    category: str
    mean_score: float
    stdev_score: float
    min_score: int
    max_score: int
    sample_count: int


class ModelEvaluation(BaseModel):
    """Complete evaluation summary for a single model.

    Attributes:
        model: Real model identifier.
        classification: Tier classification.
        overall_mean: Mean of all category means (single headline number).
        category_aggregates: Per-category aggregated statistics.
        rank: 1-indexed rank among all evaluated models.
        evaluation_count: Number of pointwise evaluations for this model.
    """

    model: str
    classification: Classification
    overall_mean: float
    category_aggregates: list[CategoryAggregate]
    rank: int = 0
    evaluation_count: int = 0


class EvaluationSummary(BaseModel):
    """Complete evaluation summary across all models.

    Attributes:
        model_evaluations: Per-model evaluation summaries, sorted by rank.
        total_evaluations: Total number of pointwise judge evaluations.
        judge_model: Model used as the judge.
        total_cost_usd: Total LLM cost incurred for this evaluation pass.
    """

    model_evaluations: list[ModelEvaluation]
    total_evaluations: int
    judge_model: str
    total_cost_usd: float = 0.0


def _classify_model(overall_mean: float) -> Classification:
    """Classify a model into a tier based on its score."""
    if overall_mean < FAIL_THRESHOLD:
        return Classification.FAIL
    if overall_mean < WARNING_THRESHOLD:
        return Classification.WARNING
    if overall_mean < CAUTION_THRESHOLD:
        return Classification.CAUTION
    return Classification.PASSED


@dataclass
class _ModelAccumulator:
    """Mutable accumulator for per-model scores during aggregation."""

    scores_by_category: dict[str, list[int]] = field(
        default_factory=lambda: defaultdict(list),
    )
    eval_count: int = 0


def _accumulate_pointwise_judgments(
    judgments_by_model: dict[str, list[PointwiseJudgment]],
) -> tuple[dict[str, _ModelAccumulator], int]:
    """Flatten pointwise judgments into per-model score accumulators.

    Args:
        judgments_by_model: Mapping of real model name to its pointwise judgments.

    Returns:
        Tuple of (model_accumulators, total_evaluation_count).
    """
    accumulators: dict[str, _ModelAccumulator] = defaultdict(_ModelAccumulator)
    total = 0

    for model_name, judgments in judgments_by_model.items():
        acc = accumulators[model_name]
        for judgment in judgments:
            total += 1
            acc.eval_count += 1

            for category, score in judgment.category_scores.items():
                acc.scores_by_category[category].append(score)

    return dict(accumulators), total


def _build_category_aggregates(
    scores_by_category: dict[str, list[int]],
) -> tuple[list[CategoryAggregate], float]:
    """Build category aggregates and compute overall mean from raw scores.

    Args:
        scores_by_category: Mapping of category name to list of scores.

    Returns:
        Tuple of (category_aggregates, overall_mean_score).
    """
    aggregates: list[CategoryAggregate] = []
    category_means: list[float] = []

    for category in CATEGORY_NAMES:
        scores = scores_by_category.get(category, [])
        if not scores:
            continue

        cat_mean = mean(scores)
        category_means.append(cat_mean)
        aggregates.append(
            CategoryAggregate(
                category=category,
                mean_score=round(cat_mean, 1),
                stdev_score=round(stdev(scores), 1) if len(scores) > 1 else 0.0,
                min_score=min(scores),
                max_score=max(scores),
                sample_count=len(scores),
            )
        )

    overall = mean(category_means) if category_means else 0.0
    return aggregates, overall


def aggregate_evaluations(
    judgments_by_model: dict[str, list[PointwiseJudgment]],
    *,
    judge_model: str = "unknown",
    total_cost_usd: float = 0.0,
) -> EvaluationSummary:
    """Aggregate pointwise judge evaluations into per-model summaries.

    Args:
        judgments_by_model: Mapping of real model name to its pointwise judgments.
        judge_model: Model identifier used as judge.
        total_cost_usd: Total LLM cost incurred for this evaluation pass.

    Returns:
        Complete evaluation summary with ranked model evaluations.
    """
    accumulators, total_evaluations = _accumulate_pointwise_judgments(
        judgments_by_model,
    )

    evaluations: list[ModelEvaluation] = []
    for model_name, acc in accumulators.items():
        category_aggregates, overall_mean = _build_category_aggregates(
            acc.scores_by_category,
        )

        evaluations.append(
            ModelEvaluation(
                model=model_name,
                classification=_classify_model(overall_mean),
                overall_mean=round(overall_mean, 1),
                category_aggregates=category_aggregates,
                evaluation_count=acc.eval_count,
            )
        )

    evaluations.sort(key=lambda e: -e.overall_mean)
    for rank, evaluation in enumerate(evaluations, start=1):
        evaluation.rank = rank

    return EvaluationSummary(
        model_evaluations=evaluations,
        total_evaluations=total_evaluations,
        judge_model=judge_model,
        total_cost_usd=total_cost_usd,
    )


class JudgmentUnit(BaseModel):
    """One immutable fixture/treatment/run/judge evaluation unit."""

    fixture_id: str
    treatment: str
    run_number: int
    judge: str
    judgment: PointwiseJudgment | None = None

    @property
    def comparison_key(self) -> tuple[str, str, int]:
        """Identity shared by judges evaluating the same treatment output."""
        return (self.fixture_id, self.treatment, self.run_number)


class JudgeReliability(BaseModel):
    """Coverage and failure statistics for one declared judge."""

    expected_units: int
    completed_units: int
    missing_rate: float
    failure_rate: float


class InterRaterAgreement(BaseModel):
    """Pairwise agreement over exact shared evaluation units."""

    judge_a: str
    judge_b: str
    shared_units: int
    mean_absolute_difference: float
    agreement: float


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Raw output from one judge, retaining exact evaluation-unit identity."""

    judgments_by_model: dict[str, list[PointwiseJudgment]]
    units: tuple[JudgmentUnit, ...] = ()
    expected_units: int = 0
    failed_units: int = 0
    total_cost_usd: float = 0.0
    reserved_cost_usd: float = 0.0
    maximum_possible_cost_usd: float = 0.0


class MultiJudgeEvaluationSummary(BaseModel):
    """Per-judge results, reliability, agreement, and weighted consensus."""

    per_judge: dict[str, EvaluationSummary]
    consensus: EvaluationSummary
    judge_weights: dict[str, float]
    reliability: dict[str, JudgeReliability]
    inter_rater_agreement: list[InterRaterAgreement]
    total_cost_usd: float = 0.0
    reserved_cost_usd: float = 0.0
    maximum_possible_cost_usd: float = 0.0


def compute_multi_judge_summary(
    judge_results: dict[str, EvaluationResult],
    judge_weights: dict[str, float] | None = None,
) -> MultiJudgeEvaluationSummary:
    """Aggregate exact judge units using declared positive consensus weights."""
    weights = judge_weights or dict.fromkeys(judge_results, 1.0)
    if set(weights) != set(judge_results):
        message = "Judge weights must match judge results exactly"
        raise ValueError(message)
    if any(weight <= 0.0 for weight in weights.values()):
        message = "Judge weights must be greater than zero"
        raise ValueError(message)

    per_judge = {
        judge: aggregate_evaluations(
            result.judgments_by_model,
            judge_model=judge,
            total_cost_usd=result.total_cost_usd,
        )
        for judge, result in judge_results.items()
    }

    consensus_evaluations: list[ModelEvaluation] = []
    treatments = {model for result in judge_results.values() for model in result.judgments_by_model}
    for treatment in treatments:
        categories: list[CategoryAggregate] = []
        category_means: list[float] = []
        for category in CATEGORY_NAMES:
            scored = [
                (weights[judge], aggregate.mean_score)
                for judge, summary in per_judge.items()
                for evaluation in summary.model_evaluations
                if evaluation.model == treatment
                for aggregate in evaluation.category_aggregates
                if aggregate.category == category
            ]
            if not scored:
                continue
            weighted_mean = sum(weight * score for weight, score in scored) / sum(weight for weight, _ in scored)
            category_means.append(weighted_mean)
            categories.append(
                CategoryAggregate(
                    category=category,
                    mean_score=round(weighted_mean, 1),
                    stdev_score=0.0,
                    min_score=round(min(score for _, score in scored)),
                    max_score=round(max(score for _, score in scored)),
                    sample_count=len(scored),
                )
            )
        overall = mean(category_means) if category_means else 0.0
        evaluation_count = sum(len(result.judgments_by_model.get(treatment, ())) for result in judge_results.values())
        consensus_evaluations.append(
            ModelEvaluation(
                model=treatment,
                classification=_classify_model(overall),
                overall_mean=round(overall, 1),
                category_aggregates=categories,
                evaluation_count=evaluation_count,
            )
        )
    consensus_evaluations.sort(key=lambda evaluation: -evaluation.overall_mean)
    for rank, evaluation in enumerate(consensus_evaluations, 1):
        evaluation.rank = rank

    agreements: list[InterRaterAgreement] = []
    judge_names = list(judge_results)
    for index, judge_a in enumerate(judge_names):
        scores_a = {
            unit.comparison_key: unit.judgment.average_score for unit in judge_results[judge_a].units if unit.judgment
        }
        for judge_b in judge_names[index + 1 :]:
            scores_b = {
                unit.comparison_key: unit.judgment.average_score
                for unit in judge_results[judge_b].units
                if unit.judgment
            }
            shared = scores_a.keys() & scores_b.keys()
            difference = mean(abs(scores_a[key] - scores_b[key]) for key in shared) if shared else 100.0
            agreements.append(
                InterRaterAgreement(
                    judge_a=judge_a,
                    judge_b=judge_b,
                    shared_units=len(shared),
                    mean_absolute_difference=round(difference, 2),
                    agreement=round(max(0.0, 1.0 - difference / 100.0), 4) if shared else 0.0,
                )
            )

    reliability = {
        judge: JudgeReliability(
            expected_units=result.expected_units,
            completed_units=sum(unit.judgment is not None for unit in result.units),
            missing_rate=round(max(0, result.expected_units - len(result.units)) / result.expected_units, 4)
            if result.expected_units
            else 0.0,
            failure_rate=round(result.failed_units / result.expected_units, 4) if result.expected_units else 0.0,
        )
        for judge, result in judge_results.items()
    }
    total_cost = sum(result.total_cost_usd for result in judge_results.values())
    reserved_cost = sum(result.reserved_cost_usd for result in judge_results.values())
    maximum_possible_cost = sum(result.maximum_possible_cost_usd for result in judge_results.values())
    return MultiJudgeEvaluationSummary(
        per_judge=per_judge,
        consensus=EvaluationSummary(
            model_evaluations=consensus_evaluations,
            total_evaluations=sum(e.evaluation_count for e in consensus_evaluations),
            judge_model="weighted-consensus",
            total_cost_usd=total_cost,
        ),
        judge_weights=weights,
        reliability=reliability,
        inter_rater_agreement=agreements,
        total_cost_usd=total_cost,
        reserved_cost_usd=reserved_cost,
        maximum_possible_cost_usd=maximum_possible_cost,
    )

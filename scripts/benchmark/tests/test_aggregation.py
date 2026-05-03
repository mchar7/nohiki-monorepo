"""Tests for score aggregation and model classification."""

from __future__ import annotations

import pytest

from llm_benchmark.schemas.aggregation import (
    CATEGORY_NAMES,
    Classification,
    EvaluationResult,
    JudgmentUnit,
    MultiJudgeEvaluationSummary,
    _build_category_aggregates,
    aggregate_evaluations,
    compute_multi_judge_summary,
)
from llm_benchmark.schemas.judge import CategoryScore, PointwiseJudgment


def _make_score(value: int = 75) -> CategoryScore:
    return CategoryScore(score=value, reasoning="Detailed reasoning for this particular score value.")


def _make_pointwise(score: int = 75) -> PointwiseJudgment:
    category = _make_score(score)
    return PointwiseJudgment(
        inference_reasonableness=category,
        description_quality=category,
        downstream_usefulness=category,
        summary="Model handled residual subjective quality consistently.",
    )


class TestClassification:
    """Tests for Classification enum."""

    def test_values(self) -> None:
        assert Classification.PASSED.value == "PASSED"
        assert Classification.CAUTION.value == "CAUTION"
        assert Classification.WARNING.value == "WARNING"
        assert Classification.FAIL.value == "FAIL"

    def test_is_str_enum(self) -> None:
        assert isinstance(Classification.PASSED, str)


class TestCategoryNames:
    """Tests for CATEGORY_NAMES constant."""

    def test_expected_residual_categories(self) -> None:
        assert CATEGORY_NAMES == (
            "inference_reasonableness",
            "description_quality",
            "downstream_usefulness",
        )


class TestAggregateEvaluations:
    """Tests for aggregate_evaluations function."""

    def test_basic_aggregation(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "google/gemini-3-flash-preview": [_make_pointwise(80)],
            "deepseek/deepseek-v3.2": [_make_pointwise(70)],
        }
        summary = aggregate_evaluations(judgments, judge_model="test-judge")

        assert summary.total_evaluations == 2
        assert summary.judge_model == "test-judge"
        assert len(summary.model_evaluations) == 2

        top_model = summary.model_evaluations[0]
        assert top_model.model == "google/gemini-3-flash-preview"
        assert top_model.rank == 1
        assert top_model.overall_mean == pytest.approx(80.0)

    def test_multiple_judgments_per_model(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "model-a": [_make_pointwise(90), _make_pointwise(80)],
            "model-b": [_make_pointwise(60), _make_pointwise(70)],
        }
        summary = aggregate_evaluations(judgments)
        assert summary.total_evaluations == 4

        model_a = next(e for e in summary.model_evaluations if e.model == "model-a")
        assert model_a.overall_mean == pytest.approx(85.0)
        assert model_a.evaluation_count == 2

    def test_low_score_classification(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "low-scorer": [_make_pointwise(35)],
        }
        summary = aggregate_evaluations(judgments)
        assert summary.model_evaluations[0].classification == Classification.FAIL

    def test_warning_classification(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "mediocre": [_make_pointwise(55)],
        }
        summary = aggregate_evaluations(judgments)
        assert summary.model_evaluations[0].classification == Classification.WARNING

    def test_caution_classification(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "decent": [_make_pointwise(70)],
        }
        summary = aggregate_evaluations(judgments)
        assert summary.model_evaluations[0].classification == Classification.CAUTION

    def test_passed_classification(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "excellent": [_make_pointwise(85)],
        }
        summary = aggregate_evaluations(judgments)
        assert summary.model_evaluations[0].classification == Classification.PASSED

    def test_empty_judgments(self) -> None:
        summary = aggregate_evaluations({})
        assert summary.total_evaluations == 0
        assert len(summary.model_evaluations) == 0

    def test_category_aggregates_present(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "test-model": [_make_pointwise(75)],
        }
        summary = aggregate_evaluations(judgments)

        model_eval = summary.model_evaluations[0]
        assert len(model_eval.category_aggregates) == 3

        categories = {ca.category for ca in model_eval.category_aggregates}
        assert categories == set(CATEGORY_NAMES)

    def test_ranking_order(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "best": [_make_pointwise(90)],
            "middle": [_make_pointwise(70)],
            "worst": [_make_pointwise(50)],
        }
        summary = aggregate_evaluations(judgments)
        ranks = [(e.model, e.rank) for e in summary.model_evaluations]
        assert ranks == [("best", 1), ("middle", 2), ("worst", 3)]


class TestBuildCategoryAggregates:
    """Tests for _build_category_aggregates function."""

    def test_empty_scores_skips_all_categories(self) -> None:
        aggregates, overall = _build_category_aggregates({})
        assert aggregates == []
        assert overall == pytest.approx(0.0)

    def test_partial_categories_skips_missing(self) -> None:
        aggregates, _ = _build_category_aggregates({"description_quality": [80, 90]})
        assert len(aggregates) == 1
        assert aggregates[0].category == "description_quality"


class TestEvaluationResult:
    """Tests for EvaluationResult dataclass."""

    def test_stores_data(self) -> None:
        judgments: dict[str, list[PointwiseJudgment]] = {
            "openrouter:model-a": [_make_pointwise()],
        }
        result = EvaluationResult(judgments_by_model=judgments)
        assert "openrouter:model-a" in result.judgments_by_model

    def test_empty_result(self) -> None:
        result = EvaluationResult(judgments_by_model={})
        assert result.judgments_by_model == {}


class TestComputeMultiJudgeSummary:
    """Tests for compute_multi_judge_summary function."""

    def _make_eval_result(
        self,
        scores_by_model: dict[str, int],
    ) -> EvaluationResult:
        return EvaluationResult(
            judgments_by_model={model: [_make_pointwise(score)] for model, score in scores_by_model.items()},
        )

    def test_per_judge_keys_match_input(self) -> None:
        judge1 = self._make_eval_result({"model-a": 85, "model-b": 65})
        judge2 = self._make_eval_result({"model-a": 80, "model-b": 70})
        summary = compute_multi_judge_summary({"judge-1": judge1, "judge-2": judge2})
        assert set(summary.per_judge.keys()) == {"judge-1", "judge-2"}

    def test_consensus_judge_model_label(self) -> None:
        judge1 = self._make_eval_result({"model-a": 80, "model-b": 70})
        summary = compute_multi_judge_summary({"judge-1": judge1})
        assert summary.consensus.judge_model == "weighted-consensus"

    def test_consensus_contains_all_models(self) -> None:
        judge1 = self._make_eval_result({"model-a": 90, "model-b": 60})
        judge2 = self._make_eval_result({"model-a": 80, "model-b": 70})
        summary = compute_multi_judge_summary({"j1": judge1, "j2": judge2})
        consensus_models = {e.model for e in summary.consensus.model_evaluations}
        assert "model-a" in consensus_models
        assert "model-b" in consensus_models

    def test_single_judge_consensus_equals_per_judge(self) -> None:
        judge1 = self._make_eval_result({"model-a": 80, "model-b": 60})
        summary = compute_multi_judge_summary({"j1": judge1})
        per_j1_models = {e.model: e.overall_mean for e in summary.per_judge["j1"].model_evaluations}
        consensus_models = {e.model: e.overall_mean for e in summary.consensus.model_evaluations}
        assert per_j1_models == consensus_models

    def test_returns_multi_judge_summary_type(self) -> None:
        judge1 = self._make_eval_result({"model-a": 75})
        result = compute_multi_judge_summary({"j1": judge1})
        assert isinstance(result, MultiJudgeEvaluationSummary)

    def test_cost_propagates_to_per_judge(self) -> None:
        judge1 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.25)
        judge2 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.50)
        summary = compute_multi_judge_summary({"j1": judge1, "j2": judge2})
        assert summary.per_judge["j1"].total_cost_usd == pytest.approx(0.25)
        assert summary.per_judge["j2"].total_cost_usd == pytest.approx(0.50)

    def test_total_cost_sums_across_judges(self) -> None:
        judge1 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.10)
        judge2 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.30)
        summary = compute_multi_judge_summary({"j1": judge1, "j2": judge2})
        assert summary.total_cost_usd == pytest.approx(0.40)

    def test_consensus_cost_equals_total(self) -> None:
        judge1 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.15)
        judge2 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.20)
        summary = compute_multi_judge_summary({"j1": judge1, "j2": judge2})
        assert summary.consensus.total_cost_usd == pytest.approx(0.35)

    def test_single_judge_cost(self) -> None:
        judge1 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.42)
        summary = compute_multi_judge_summary({"j1": judge1})
        assert summary.total_cost_usd == pytest.approx(0.42)
        assert summary.per_judge["j1"].total_cost_usd == pytest.approx(0.42)

    def test_judge_weights_change_consensus_ranking(self) -> None:
        judge_a = self._make_eval_result({"synthetic:a": 95, "synthetic:b": 40})
        judge_b = self._make_eval_result({"synthetic:a": 40, "synthetic:b": 95})

        favors_a = compute_multi_judge_summary(
            {"judge-a": judge_a, "judge-b": judge_b},
            {"judge-a": 4.0, "judge-b": 1.0},
        )
        favors_b = compute_multi_judge_summary(
            {"judge-a": judge_a, "judge-b": judge_b},
            {"judge-a": 1.0, "judge-b": 4.0},
        )

        assert favors_a.consensus.model_evaluations[0].model == "synthetic:a"
        assert favors_b.consensus.model_evaluations[0].model == "synthetic:b"

    def test_reliability_and_agreement_use_exact_declared_units(self) -> None:
        shared_a = JudgmentUnit(
            fixture_id="synthetic-fixture-1",
            treatment="synthetic:candidate",
            run_number=1,
            judge="synthetic:judge-a",
            judgment=_make_pointwise(80),
        )
        failed_a = JudgmentUnit(
            fixture_id="synthetic-fixture-2",
            treatment="synthetic:candidate",
            run_number=1,
            judge="synthetic:judge-a",
        )
        shared_b = shared_a.model_copy(
            update={"judge": "synthetic:judge-b", "judgment": _make_pointwise(60)},
        )
        unmatched_b = JudgmentUnit(
            fixture_id="synthetic-fixture-3",
            treatment="synthetic:candidate",
            run_number=1,
            judge="synthetic:judge-b",
            judgment=_make_pointwise(90),
        )
        summary = compute_multi_judge_summary(
            {
                "synthetic:judge-a": EvaluationResult(
                    judgments_by_model={"synthetic:candidate": [_make_pointwise(80)]},
                    units=(shared_a, failed_a),
                    expected_units=3,
                    failed_units=1,
                ),
                "synthetic:judge-b": EvaluationResult(
                    judgments_by_model={"synthetic:candidate": [_make_pointwise(60), _make_pointwise(90)]},
                    units=(shared_b, unmatched_b),
                    expected_units=2,
                ),
            },
        )

        reliability_a = summary.reliability["synthetic:judge-a"]
        assert reliability_a.completed_units == 1
        assert reliability_a.missing_rate == pytest.approx(0.3333)
        assert reliability_a.failure_rate == pytest.approx(0.3333)
        reliability_b = summary.reliability["synthetic:judge-b"]
        assert reliability_b.completed_units == 2
        assert reliability_b.missing_rate == pytest.approx(0.0)
        assert reliability_b.failure_rate == pytest.approx(0.0)

        agreement = summary.inter_rater_agreement[0]
        assert agreement.shared_units == 1
        assert agreement.mean_absolute_difference == pytest.approx(20.0)
        assert agreement.agreement == pytest.approx(0.8)


class TestMultiJudgeEvaluationSummary:
    """Tests for MultiJudgeEvaluationSummary Pydantic model."""

    def test_json_round_trip(self) -> None:
        judge_eval = EvaluationResult(
            judgments_by_model={"model-a": [_make_pointwise()]},
        )
        summary = compute_multi_judge_summary({"test-judge": judge_eval})
        json_str = summary.model_dump_json()
        restored = MultiJudgeEvaluationSummary.model_validate_json(json_str)
        assert restored.consensus.judge_model == "weighted-consensus"
        assert set(restored.per_judge.keys()) == {"test-judge"}

"""Tests for Rich TUI display components."""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO

from rich.console import Console

from llm_benchmark.display.panels import (
    _format_score,
    _score_color,
    display_available_fixtures,
    display_benchmark_results,
    display_cost_estimate,
    display_evaluation_results,
    display_multi_judge_results,
)
from llm_benchmark.display.progress import (
    create_benchmark_progress,
    create_evaluation_progress,
)
from llm_benchmark.schemas.aggregation import (
    CategoryAggregate,
    Classification,
    EvaluationResult,
    EvaluationSummary,
    ModelEvaluation,
    compute_multi_judge_summary,
)
from llm_benchmark.schemas.metrics import BenchmarkResult as _BenchmarkResult
from llm_benchmark.schemas.metrics import ModelResult, RunResult


class BenchmarkResult(_BenchmarkResult):
    experiment_fingerprint: str = "test-experiment"


type DisplayFunc = Callable[..., object]


def _capture_console_output(func: DisplayFunc, *args: object) -> str:
    """Capture Rich console output as plain text."""
    buf = StringIO()
    import llm_benchmark.display.panels as panels_module

    original = panels_module.console
    panels_module.console = Console(file=buf, force_terminal=False, width=120)
    try:
        func(*args)
    finally:
        panels_module.console = original
    return buf.getvalue()


class TestScoreColor:
    """Tests for _score_color function."""

    def test_high_score_green(self) -> None:
        assert _score_color(85) == "green"

    def test_medium_score_yellow(self) -> None:
        assert _score_color(65) == "yellow"

    def test_low_score_bright_red(self) -> None:
        assert _score_color(45) == "bright_red"

    def test_very_low_score_red(self) -> None:
        assert _score_color(30) == "red"

    def test_boundary_80(self) -> None:
        assert _score_color(80) == "green"

    def test_boundary_60(self) -> None:
        assert _score_color(60) == "yellow"

    def test_boundary_40(self) -> None:
        assert _score_color(40) == "bright_red"


class TestFormatScore:
    """Tests for _format_score function."""

    def test_format_high_score(self) -> None:
        result = _format_score(90.0)
        assert "90.0" in result
        assert "green" in result

    def test_format_low_score(self) -> None:
        result = _format_score(30.0)
        assert "30.0" in result
        assert "red" in result


class TestDisplayCostEstimate:
    """Tests for display_cost_estimate function."""

    def test_returns_total_cost(self) -> None:
        output = _capture_console_output(
            display_cost_estimate,
            ["openrouter:google/gemini-3-flash-preview"],
            2,
            1,
        )
        assert "Cost Estimate" in output
        assert "$" in output

    def test_displays_model_names(self) -> None:
        output = _capture_console_output(
            display_cost_estimate,
            ["openrouter:google/gemini-3-flash-preview", "openrouter:deepseek/deepseek-v3.2"],
            1,
            1,
        )
        assert "gemini-3-flash-preview" in output
        assert "deepseek-v3.2" in output


class TestDisplayBenchmarkResults:
    """Tests for display_benchmark_results function."""

    def test_renders_without_error(self) -> None:
        result = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "test/model": ModelResult(
                    model="test/model",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            treatment_fingerprint="test-treatment",
                            cell_fingerprint="test-cell",
                            run_number=1,
                            success=True,
                            latency_ms=1000.0,
                            input_tokens=100,
                            output_tokens=50,
                            retry_count=0,
                        ),
                    ],
                ),
            },
        )
        output = _capture_console_output(display_benchmark_results, result)
        assert "test/model" in output
        assert "Benchmark Execution Summary" in output

    def test_unknown_retry_aggregates_render_n_a(self) -> None:
        # All runs failed with unmeasured retries -> avg/stdev are None -> rendered "n/a", never a fake 0.
        result = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "test/model": ModelResult(
                    model="test/model",
                    total_cost_usd=0.0,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            treatment_fingerprint="test-treatment",
                            cell_fingerprint="test-cell",
                            run_number=1,
                            success=False,
                            latency_ms=1000.0,
                            retry_count=None,
                        ),
                    ],
                ),
            },
        )
        output = _capture_console_output(display_benchmark_results, result)
        assert "n/a" in output

    def test_measured_zero_retry_renders_numeric_not_n_a(self) -> None:
        # A genuine measured zero must show as a number (0.00), distinct from "n/a".
        result = BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=1,
            models={
                "test/model": ModelResult(
                    model="test/model",
                    total_cost_usd=0.01,
                    runs=[
                        RunResult(
                            fixture_id="f1",
                            treatment_fingerprint="test-treatment",
                            cell_fingerprint="test-cell",
                            run_number=1,
                            success=True,
                            latency_ms=1000.0,
                            retry_count=0,
                        ),
                    ],
                ),
            },
        )
        output = _capture_console_output(display_benchmark_results, result)
        assert "0.00" in output
        assert "n/a" not in output


class TestDisplayEvaluationResults:
    """Tests for display_evaluation_results function."""

    def test_renders_rankings(self) -> None:
        summary = EvaluationSummary(
            model_evaluations=[
                ModelEvaluation(
                    model="best/model",
                    classification=Classification.PASSED,
                    overall_mean=85.0,
                    category_aggregates=[
                        CategoryAggregate(
                            category=cat,
                            mean_score=85.0,
                            stdev_score=2.0,
                            min_score=80,
                            max_score=90,
                            sample_count=3,
                        )
                        for cat in [
                            "location_accuracy",
                            "compensation_accuracy",
                            "skills_extraction",
                            "experience_assessment",
                            "metadata_normalization",
                            "description_fidelity",
                            "data_adherence",
                            "overall_quality",
                        ]
                    ],
                    rank=1,
                    evaluation_count=3,
                ),
            ],
            total_evaluations=3,
            judge_model="test-judge",
        )
        output = _capture_console_output(display_evaluation_results, summary)
        assert "best/model" in output
        assert "PASSED" in output


class TestDisplayBenchmarkResultsPassRates:
    """Tests for pass_rate colour branches in display_benchmark_results."""

    def _make_result_with_pass_rate(self, successes: int, total: int) -> BenchmarkResult:
        """Return a BenchmarkResult whose single model has the given success ratio."""
        runs = [
            RunResult(
                fixture_id="f1",
                treatment_fingerprint="test-treatment",
                cell_fingerprint="test-cell",
                run_number=i + 1,
                success=(i < successes),
                latency_ms=100.0,
                input_tokens=50,
                output_tokens=20,
                retry_count=0,
            )
            for i in range(total)
        ]
        return BenchmarkResult(
            fixtures_used=["f1"],
            runs_per_fixture=total,
            models={
                "test/model": ModelResult(
                    model="test/model",
                    total_cost_usd=0.01,
                    runs=runs,
                ),
            },
        )

    def test_yellow_pass_rate_branch(self) -> None:
        result = self._make_result_with_pass_rate(successes=1, total=2)
        output = _capture_console_output(display_benchmark_results, result)
        assert "test/model" in output

    def test_red_pass_rate_branch(self) -> None:
        result = self._make_result_with_pass_rate(successes=0, total=2)
        output = _capture_console_output(display_benchmark_results, result)
        assert "test/model" in output


class TestDisplayAvailableFixtures:
    """Tests for display_available_fixtures function."""

    def test_renders_fixture_list(self) -> None:
        output = _capture_console_output(
            display_available_fixtures,
            ["fixture_a", "fixture_b", "fixture_c"],
        )
        assert "fixture_a" in output
        assert "fixture_b" in output
        assert "fixture_c" in output


def _make_minimal_evaluation_summary(judge_model: str = "test-judge") -> EvaluationSummary:
    """Return a minimal EvaluationSummary for display tests."""
    return EvaluationSummary(
        model_evaluations=[
            ModelEvaluation(
                model="test/model",
                classification=Classification.PASSED,
                overall_mean=85.0,
                category_aggregates=[
                    CategoryAggregate(
                        category=cat,
                        mean_score=85.0,
                        stdev_score=2.0,
                        min_score=80,
                        max_score=90,
                        sample_count=1,
                    )
                    for cat in [
                        "location_accuracy",
                        "compensation_accuracy",
                        "skills_extraction",
                        "experience_assessment",
                        "metadata_normalization",
                        "description_fidelity",
                        "data_adherence",
                        "overall_quality",
                    ]
                ],
                rank=1,
                evaluation_count=1,
            ),
        ],
        total_evaluations=1,
        judge_model=judge_model,
    )


class TestDisplayMultiJudgeResults:
    """Tests for display_multi_judge_results function."""

    def test_renders_single_judge_no_consensus_panel(self) -> None:
        result = EvaluationResult(judgments_by_model={})
        summary = compute_multi_judge_summary({"only-judge": result})
        output = _capture_console_output(display_multi_judge_results, summary)
        assert "only-judge" in output

    def test_renders_multiple_judges_with_consensus(self) -> None:
        result_1 = EvaluationResult(judgments_by_model={})
        result_2 = EvaluationResult(judgments_by_model={})
        summary = compute_multi_judge_summary({"judge-1": result_1, "judge-2": result_2})
        output = _capture_console_output(display_multi_judge_results, summary)
        assert "judge-1" in output
        assert "judge-2" in output
        assert "Consensus" in output or "consensus" in output

    def test_single_judge_shows_total_cost(self) -> None:
        result = EvaluationResult(judgments_by_model={}, total_cost_usd=0.1234)
        summary = compute_multi_judge_summary({"only-judge": result})
        output = _capture_console_output(display_multi_judge_results, summary)
        assert "$0.1234" in output
        assert "Total evaluation cost" in output

    def test_multi_judge_shows_per_judge_cost(self) -> None:
        r1 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.25)
        r2 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.50)
        summary = compute_multi_judge_summary({"judge-1": r1, "judge-2": r2})
        output = _capture_console_output(display_multi_judge_results, summary)
        assert "$0.2500" in output
        assert "$0.5000" in output

    def test_multi_judge_shows_cost_summary_table(self) -> None:
        r1 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.10)
        r2 = EvaluationResult(judgments_by_model={}, total_cost_usd=0.30)
        summary = compute_multi_judge_summary({"judge-1": r1, "judge-2": r2})
        output = _capture_console_output(display_multi_judge_results, summary)
        assert "Cost Summary" in output
        assert "$0.4000" in output


class TestProgressFactories:
    def test_create_benchmark_progress_returns_progress(self) -> None:
        from rich.progress import Progress

        progress = create_benchmark_progress()
        assert isinstance(progress, Progress)

    def test_create_evaluation_progress_returns_progress(self) -> None:
        from rich.progress import Progress

        progress = create_evaluation_progress()
        assert isinstance(progress, Progress)

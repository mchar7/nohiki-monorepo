"""Rich TUI panels for benchmark and evaluation results display.

Provides formatted tables and panels for CLI output of benchmark execution
results, cost estimates, evaluation summaries, and fixture listings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.usage import RequestUsage
from rich.panel import Panel
from rich.table import Table

from llm_benchmark.config.constants import (
    ESTIMATED_INPUT_TOKENS_PER_CALL,
    ESTIMATED_OUTPUT_TOKENS_PER_CALL,
)
from llm_benchmark.display.console import console
from llm_benchmark.schemas.aggregation import CATEGORY_NAMES, Classification

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nohiki_llm_client import LLMModelConfig

    from llm_benchmark.pricing import PricingSnapshot
    from llm_benchmark.schemas.aggregation import EvaluationSummary, ModelEvaluation, MultiJudgeEvaluationSummary
    from llm_benchmark.schemas.metrics import BenchmarkResult

_UNKNOWN_VALUE: str = "[dim]?[/dim]"

_CLASSIFICATION_COLORS: dict[Classification, str] = {
    Classification.PASSED: "bold green",
    Classification.CAUTION: "bold yellow",
    Classification.WARNING: "bold bright_red",
    Classification.FAIL: "bold red",
}

_CATEGORY_LABELS: dict[str, str] = {
    "location_accuracy": "Location",
    "compensation_accuracy": "Compensation",
    "skills_extraction": "Skills",
    "experience_assessment": "Experience",
    "metadata_normalization": "Metadata",
    "description_fidelity": "Description",
    "data_adherence": "Adherence",
    "overall_quality": "Overall",
}


def display_cost_estimate(
    models: Sequence[str | LLMModelConfig],
    fixtures_count: int,
    runs_per_fixture: int,
    *,
    snapshots: Sequence[PricingSnapshot] | None = None,
) -> float:
    """Display cost estimate table and return total estimated cost.

    String entries use generic genai-prices model-level rates. ``LLMModelConfig``
    entries use route-aware :class:`PricingSnapshot` pricing -- pre-resolved
    ``snapshots`` (index-aligned) when supplied, otherwise resolved per config --
    so an explicitly routed OpenRouter treatment shows its selected-endpoint rate
    rather than the model-level rate.

    Args:
        models: Model identifiers or configs in treatment order.
        fixtures_count: Number of test fixtures.
        runs_per_fixture: Runs per fixture per model.
        snapshots: Optional pre-resolved pricing snapshots, index-aligned with ``models``.

    Returns:
        Total estimated cost in USD (sum of known costs; unknown models contribute 0).
    """
    from llm_benchmark.pricing import calc_cost, get_per_million_prices, resolve_pricing_snapshot

    table = Table(title="Cost Estimate per Model")
    table.add_column("Model", style="cyan")
    table.add_column("Input $/M", justify="right")
    table.add_column("Output $/M", justify="right")
    table.add_column("Est. Cost", justify="right", style="green")

    total_calls = fixtures_count * runs_per_fixture
    est_input = ESTIMATED_INPUT_TOKENS_PER_CALL * total_calls
    est_output = ESTIMATED_OUTPUT_TOKENS_PER_CALL * total_calls
    resolved = list(snapshots) if snapshots is not None else [None] * len(models)
    total_cost = 0.0
    for model, snapshot in zip(models, resolved, strict=True):
        if snapshot is not None:
            label = model if isinstance(model, str) else model.model
            input_per_m, output_per_m = snapshot.per_million()
            est_cost = snapshot.calc_cost(est_input, est_output)
        elif isinstance(model, str):
            label = model
            input_per_m, output_per_m = get_per_million_prices(model)
            est_cost = calc_cost(RequestUsage(input_tokens=est_input, output_tokens=est_output), model)
        else:
            snap = resolve_pricing_snapshot(model)
            label = model.model
            input_per_m, output_per_m = snap.per_million()
            est_cost = snap.calc_cost(est_input, est_output)
        if est_cost is not None:
            total_cost += est_cost
        table.add_row(
            label,
            f"${input_per_m:.3f}" if input_per_m is not None else _UNKNOWN_VALUE,
            f"${output_per_m:.3f}" if output_per_m is not None else _UNKNOWN_VALUE,
            f"${est_cost:.4f}" if est_cost is not None else _UNKNOWN_VALUE,
        )

    console.print(table)
    total_llm_calls = len(models) * fixtures_count * runs_per_fixture
    console.print(f"\n[bold]Total estimated cost:[/bold] [green]${total_cost:.4f}[/green]")
    console.print(
        f"[dim]({len(models)} models x {fixtures_count} fixtures x {runs_per_fixture} runs "
        f"= {total_llm_calls} total LLM calls)[/dim]\n"
    )

    return total_cost


def display_benchmark_results(result: BenchmarkResult) -> None:
    """Display benchmark execution results in rich tables.

    Args:
        result: Complete benchmark result with per-model metrics.
    """
    summary_table = Table(title="Benchmark Execution Summary")
    summary_table.add_column("Model", style="cyan")
    summary_table.add_column("Pass Rate", justify="right")
    summary_table.add_column("Avg Latency", justify="right")
    summary_table.add_column("Latency StdDev", justify="right")
    summary_table.add_column("Avg Tokens", justify="right")
    summary_table.add_column("Actual Cost", justify="right", style="green")
    summary_table.add_column("Avg Retries", justify="right")
    summary_table.add_column("Retry SD", justify="right")

    sorted_models = sorted(
        result.models.items(),
        key=lambda x: (-x[1].pass_rate, x[1].avg_latency_ms),
    )

    for name, metrics in sorted_models:
        if metrics.pass_rate >= 0.9:
            rate_color = "green"
        elif metrics.pass_rate >= 0.5:
            rate_color = "yellow"
        else:
            rate_color = "red"
        summary_table.add_row(
            name,
            f"[{rate_color}]{metrics.pass_rate:.1%}[/{rate_color}]",
            f"{metrics.avg_latency_ms:,.0f}ms",
            f"{metrics.latency_stdev_ms:,.0f}ms",
            f"{metrics.avg_input_tokens + metrics.avg_output_tokens:,.0f}",
            f"${metrics.total_cost_usd:.4f}",
            "n/a" if metrics.avg_retry_count is None else f"{metrics.avg_retry_count:.2f}",
            "n/a" if metrics.retry_count_stdev is None else f"{metrics.retry_count_stdev:.2f}",
        )

    console.print(summary_table)

    comparison_panel = Panel(
        f"[bold green]Fastest:[/bold green] {result.get_fastest_model() or 'N/A'}\n"
        f"[bold blue]Cheapest:[/bold blue] {result.get_cheapest_model() or 'N/A'}\n"
        f"[bold yellow]Most Consistent:[/bold yellow] {result.get_most_consistent_model() or 'N/A'}",
        title="Winner Comparison",
    )
    console.print(comparison_panel)
    console.print(f"\n[bold]Total actual cost:[/bold] [green]${result.total_actual_cost:.4f}[/green]")


def _score_color(score: float) -> str:
    """Return Rich color markup for a numeric score.

    Args:
        score: Score value (0-100).

    Returns:
        Rich color string.
    """
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    if score >= 40:
        return "bright_red"
    return "red"


def _format_score(score: float) -> str:
    """Format a score with color markup.

    Args:
        score: Score value (0-100).

    Returns:
        Rich-formatted score string.
    """
    color = _score_color(score)
    return f"[{color}]{score:.1f}[/{color}]"


def _display_model_detail(evaluation: ModelEvaluation) -> None:
    """Display detailed category scores for a single model.

    Args:
        evaluation: Model evaluation with category aggregates.
    """
    detail_table = Table(
        title=f"Category Detail: {evaluation.model}",
        show_lines=True,
    )
    detail_table.add_column("Category", style="cyan")
    detail_table.add_column("Mean", justify="right")
    detail_table.add_column("StdDev", justify="right")
    detail_table.add_column("Min", justify="right")
    detail_table.add_column("Max", justify="right")
    detail_table.add_column("N", justify="right", style="dim")

    cat_map = {ca.category: ca for ca in evaluation.category_aggregates}
    for category in CATEGORY_NAMES:
        label = _CATEGORY_LABELS.get(category, category)
        if ca := cat_map.get(category):
            detail_table.add_row(
                label,
                _format_score(ca.mean_score),
                f"{ca.stdev_score:.1f}",
                str(ca.min_score),
                str(ca.max_score),
                str(ca.sample_count),
            )
        else:
            detail_table.add_row(label, "[dim]N/A[/dim]", "", "", "", "0")

    console.print(detail_table)



def display_evaluation_results(summary: EvaluationSummary) -> None:
    """Display complete evaluation results with rankings and category detail.

    Args:
        summary: Aggregated evaluation summary from the judge.
    """
    console.print(f"\n[bold]Judge Model:[/bold] {summary.judge_model}")
    console.print(f"[bold]Total Evaluations:[/bold] {summary.total_evaluations}\n")

    ranking_table = Table(title="Model Rankings")
    ranking_table.add_column("#", justify="right", style="bold")
    ranking_table.add_column("Model", style="cyan")
    ranking_table.add_column("Classification", justify="center")
    ranking_table.add_column("Overall", justify="right")
    ranking_table.add_column("Evals", justify="right", style="dim")

    for evaluation in summary.model_evaluations:
        cls_color = _CLASSIFICATION_COLORS.get(evaluation.classification, "white")
        ranking_table.add_row(
            str(evaluation.rank),
            evaluation.model,
            f"[{cls_color}]{evaluation.classification.value}[/{cls_color}]",
            _format_score(evaluation.overall_mean),
            str(evaluation.evaluation_count),
        )

    console.print(ranking_table)

    for evaluation in summary.model_evaluations:
        console.print()
        _display_model_detail(evaluation)


def _format_cost(cost: float) -> str:
    """Format a USD cost value with color markup.

    Args:
        cost: Cost in USD.

    Returns:
        Rich-formatted cost string.
    """
    return f"[green]${cost:.4f}[/green]"


def display_multi_judge_results(summary: MultiJudgeEvaluationSummary) -> None:
    """Display combined results from a multi-judge evaluation.

    Renders each judge's full evaluation summary followed by the consensus
    summary that pools all judges' resolved judgments. Includes per-judge
    cost breakdowns and a total cost summary.

    Args:
        summary: Multi-judge evaluation summary with per-judge and consensus data.
    """
    for judge_model, judge_summary in summary.per_judge.items():
        console.print(
            Panel.fit(
                f"[bold]Judge:[/bold] {judge_model}\n[bold]Cost:[/bold] {_format_cost(judge_summary.total_cost_usd)}",
                border_style="blue",
            )
        )
        display_evaluation_results(judge_summary)

    if len(summary.per_judge) > 1:
        console.print(
            Panel.fit(
                f"[bold]Consensus[/bold] across {len(summary.per_judge)} judges",
                border_style="green",
            )
        )
        display_evaluation_results(summary.consensus)

        cost_table = Table(title="Evaluation Cost Summary")
        cost_table.add_column("Judge", style="cyan")
        cost_table.add_column("Evaluations", justify="right", style="dim")
        cost_table.add_column("Cost", justify="right", style="green")

        for judge_model, judge_summary in summary.per_judge.items():
            short = judge_model.rsplit("/", maxsplit=1)[-1] if "/" in judge_model else judge_model
            cost_table.add_row(
                short,
                str(judge_summary.total_evaluations),
                f"${judge_summary.total_cost_usd:.4f}",
            )

        cost_table.add_section()
        total_evals = sum(s.total_evaluations for s in summary.per_judge.values())
        cost_table.add_row(
            "[bold]Total[/bold]",
            f"[bold]{total_evals}[/bold]",
            f"[bold]${summary.total_cost_usd:.4f}[/bold]",
        )
        console.print(cost_table)
    else:
        console.print(f"\n[bold]Total evaluation cost:[/bold] {_format_cost(summary.total_cost_usd)}")


def display_available_fixtures(fixture_ids: list[str]) -> None:
    """Display list of available test fixtures.

    Args:
        fixture_ids: Sorted list of fixture ID strings.
    """
    console.print("[bold]Available fixtures:[/bold]")
    for fixture_id in fixture_ids:
        console.print(f"  • {fixture_id}")

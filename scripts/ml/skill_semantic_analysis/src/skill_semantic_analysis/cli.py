"""CLI for skill semantic similarity threshold analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from skill_semantic_analysis.analysis import (
    AnalysisReport,
    ThresholdMetrics,
    run_threshold_analysis,
)
from skill_semantic_analysis.analysis.test_pairs import get_all_test_pairs

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
DEFAULT_OUTPUT: Final[Path] = SCRIPT_DIR / "threshold_analysis_results.json"
DEFAULT_MODEL: Final[str] = "TechWolf/JobBERT-v2"

# Display constants
THRESHOLD_EPSILON: Final[float] = 0.005
MAX_DISPLAY_ITEMS: Final[int] = 10
QUICK_CHECK_THRESHOLD: Final[float] = 0.80

app = typer.Typer(
    name="skill-semantic",
    help="Semantic similarity threshold analysis for skill matching.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console(stderr=True)


@app.command("analyze")
def analyze(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output path for JSON report."),
    ] = DEFAULT_OUTPUT,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Sentence transformer model."),
    ] = DEFAULT_MODEL,
) -> None:
    """Run semantic similarity threshold analysis on skill pairs.

    Tests many skill pairs to find optimal threshold boundaries for auto-matching.
    """
    console.print()
    console.print(
        Panel.fit(
            f"[bold blue]Skill Semantic Similarity Analysis[/bold blue]\n[dim]Model: {model}[/dim]",
            border_style="blue",
        )
    )
    console.print()

    test_pairs = get_all_test_pairs()
    console.print(f"[dim]Loaded {len(test_pairs)} test pairs[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running analysis...", total=None)
        report = run_threshold_analysis(
            model_name=model,
            test_pairs=test_pairs,
            progress_callback=lambda msg: progress.update(task, description=msg),
        )

    _display_summary(report)
    _display_threshold_table(report.threshold_metrics, report.best_threshold)
    _display_problems(report)

    report.save(output)
    console.print(f"\n[green]✓[/green] Report saved to [cyan]{output}[/cyan]")


@app.command("quick")
def quick_check(
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Sentence transformer model."),
    ] = DEFAULT_MODEL,
) -> None:
    """Quick check: test a few key pairs without full analysis."""
    console.print()
    console.print(
        Panel.fit(
            f"[bold blue]Quick Semantic Check[/bold blue]\n[dim]Model: {model}[/dim]",
            border_style="blue",
        )
    )
    console.print()

    import numpy as np
    from sentence_transformers import SentenceTransformer

    quick_pairs = [
        ("python", "python3", True),
        ("javascript", "js", True),
        ("kubernetes", "k8s", True),
        ("react", "angular", False),
        ("python", "java", False),
        ("docker", "kubernetes", False),
    ]

    with console.status("[bold green]Loading model..."):
        st_model = SentenceTransformer(model)

    table = Table(title="Quick Similarity Check", show_header=True)
    table.add_column("Skill A", style="cyan")
    table.add_column("Skill B", style="cyan")
    table.add_column("Similarity", justify="right")
    table.add_column("Expected", justify="center")
    table.add_column("Result", justify="center")

    for skill_a, skill_b, should_match in quick_pairs:
        emb_a = st_model.encode(skill_a.lower(), normalize_embeddings=True)
        emb_b = st_model.encode(skill_b.lower(), normalize_embeddings=True)
        similarity = float(np.dot(emb_a, emb_b))

        expected = "[green]match[/green]" if should_match else "[red]no match[/red]"
        would_match = similarity >= QUICK_CHECK_THRESHOLD
        correct = would_match == should_match
        result = "[green]✓[/green]" if correct else "[red]✗[/red]"

        table.add_row(skill_a, skill_b, f"{similarity:.4f}", expected, result)

    console.print(table)


@app.command("report")
def show_report(
    input_path: Annotated[
        Path,
        typer.Argument(help="Path to analysis report JSON."),
    ],
) -> None:
    """Display a previously generated analysis report."""
    if not input_path.exists():
        console.print(f"[red]Report not found: {input_path}[/red]")
        raise typer.Exit(1)

    try:
        report = AnalysisReport.load(input_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        console.print(f"[red]Invalid report: {error}[/red]")
        raise typer.Exit(1) from error
    console.print(f"[dim]Loaded report from: {input_path}[/dim]\n")

    _display_summary(report)
    _display_threshold_table(report.threshold_metrics, report.best_threshold)
    _display_problems(report)


def _display_summary(report: AnalysisReport) -> None:
    """Display analysis summary."""
    table = Table(title="Analysis Summary", show_header=False, box=None)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total pairs tested", str(report.total_pairs))
    table.add_row("True positive pairs", str(report.true_positive_count))
    table.add_row("True negative pairs", str(report.true_negative_count))
    table.add_row("", "")
    table.add_row("Min TP similarity", f"{report.min_tp_similarity:.4f}")
    table.add_row("Max TN similarity", f"{report.max_tn_similarity:.4f}")
    table.add_row("Separation gap", f"{report.separation_gap:.4f}")
    table.add_row("", "")
    table.add_row("[bold cyan]Best threshold[/bold cyan]", f"[bold cyan]{report.best_threshold:.2f}[/bold cyan]")
    table.add_row("[bold cyan]Best F1 score[/bold cyan]", f"[bold cyan]{report.best_f1:.4f}[/bold cyan]")

    console.print(table)
    console.print()


def _display_threshold_table(metrics: list[ThresholdMetrics], best: float) -> None:
    """Display threshold analysis table."""
    table = Table(title="Threshold Analysis", show_header=True)
    table.add_column("Threshold", justify="right")
    table.add_column("Precision", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("F1", justify="right")
    table.add_column("TP", justify="right")
    table.add_column("FP", justify="right")

    key_thresholds = {0.65, 0.70, 0.75, 0.80, 0.85, 0.90, round(best, 2)}
    for m in metrics:
        if round(m.threshold, 2) in key_thresholds:
            style = "bold green" if abs(m.threshold - best) < THRESHOLD_EPSILON else ""
            table.add_row(
                f"{m.threshold:.2f}",
                f"{m.precision:.4f}",
                f"{m.recall:.4f}",
                f"{m.f1:.4f}",
                str(m.tp),
                str(m.fp),
                style=style,
            )

    console.print(table)
    console.print()


def _display_problems(report: AnalysisReport) -> None:
    """Display missed matches and false positives."""
    if report.missed_matches:
        count = len(report.missed_matches)
        threshold = report.best_threshold
        console.print(f"[yellow]⚠ {count} true positives missed at threshold {threshold:.2f}:[/yellow]")
        for item in report.missed_matches[:MAX_DISPLAY_ITEMS]:
            pair_a, pair_b = item["pair"][0], item["pair"][1]
            console.print(f"  [dim]{pair_a:25} ↔ {pair_b:25} = {item['similarity']:.4f}[/dim]")
        if len(report.missed_matches) > MAX_DISPLAY_ITEMS:
            extra = len(report.missed_matches) - MAX_DISPLAY_ITEMS
            console.print(f"  [dim]... and {extra} more[/dim]")
        console.print()

    if report.false_positives:
        console.print(
            f"[red]✗ {len(report.false_positives)} false positives at threshold {report.best_threshold:.2f}:[/red]"
        )
        for item in report.false_positives[:MAX_DISPLAY_ITEMS]:
            pair_a, pair_b = item["pair"][0], item["pair"][1]
            console.print(f"  [dim]{pair_a:25} ↔ {pair_b:25} = {item['similarity']:.4f}[/dim]")
        console.print()
    else:
        console.print("[green]✓ No false positives at this threshold[/green]\n")


if __name__ == "__main__":
    app()

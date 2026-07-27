"""Typer CLI for skill threshold calibration.

Provides commands for:
- analyze: Run calibration analysis on Tabiya skill data
- report: Generate detailed report from analysis results
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Final

import typer

from calibrate_skill_thresholds.analysis import (
    AnalysisResults,
    CalibrationReport,
    DistributionStats,
    JaccardAnalyzer,
    SimilarityResult,
    ThresholdAnalysis,
)
from calibrate_skill_thresholds.data import (
    CalibrationDataset,
    PairGenerator,
    TabiyaLoader,
    _deduplicate_pairs,
)
from calibrate_skill_thresholds.display import (
    console,
    create_progress,
    create_spinner_progress,
    print_config_snippet,
    print_dataset_summary,
    print_distribution_stats,
    print_error,
    print_false_negative_examples,
    print_false_positive_examples,
    print_header,
    print_recommendation,
    print_report_saved,
    print_threshold_analysis_table,
)

SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = SCRIPT_DIR.parents[2]
DEFAULT_CSV_PATH: Final[Path] = REPO_ROOT / "data" / "tabiya" / "skills.csv"
DEFAULT_OUTPUT_PATH: Final[Path] = SCRIPT_DIR / "calibration_report.json"

app = typer.Typer(
    name="calibrate-skill-thresholds",
    help="Empirically calibrate skill normalization thresholds using real taxonomy data.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.command("analyze")
def analyze(
    csv_path: Annotated[
        Path,
        typer.Option(
            "--csv-path",
            "-c",
            help="Path to Tabiya skills CSV file.",
        ),
    ] = DEFAULT_CSV_PATH,
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Output path for JSON report.",
        ),
    ] = DEFAULT_OUTPUT_PATH,
    max_synonyms: Annotated[
        int,
        typer.Option(
            "--max-synonyms",
            min=1,
            help="Maximum synonym pairs to analyze.",
        ),
    ] = 100000,
    max_distinct: Annotated[
        int,
        typer.Option(
            "--max-distinct",
            min=1,
            help="Maximum distinct-but-similar pairs to analyze.",
        ),
    ] = 50000,
    seed: Annotated[
        int,
        typer.Option(
            "--seed",
            help="Random seed for reproducibility.",
        ),
    ] = 42,
    show_examples: Annotated[
        bool,
        typer.Option(
            "--show-examples/--no-examples",
            help="Show false positive/negative examples.",
        ),
    ] = True,
) -> None:
    """Analyze Jaccard similarity thresholds using Tabiya skill data.

    Loads skills from CSV, generates test pairs, computes similarities,
    and recommends optimal thresholds for auto-canonicalization.
    """
    print_header()

    if not csv_path.is_file():
        print_error(f"CSV file not found: {csv_path}")
        raise typer.Exit(1)

    dataset = _load_and_generate_dataset(csv_path, max_synonyms, max_distinct, seed)
    results = _run_analysis(dataset)
    report = _generate_report(results)

    _display_results(report, show_examples=show_examples)
    _save_report(report, output)

    print_config_snippet(report.zero_fp_threshold, report.results.distinct_stats.count)


@app.command("quick")
def quick_check(
    csv_path: Annotated[
        Path,
        typer.Option("--csv-path", "-c"),
    ] = DEFAULT_CSV_PATH,
) -> None:
    """Quick check: load data and show basic statistics without full analysis."""
    print_header()

    if not csv_path.is_file():
        print_error(f"CSV file not found: {csv_path}")
        raise typer.Exit(1)

    with create_spinner_progress() as progress:
        task = progress.add_task("Loading skills...", total=None)
        loader = TabiyaLoader(csv_path)
        skills = loader.load()
        progress.update(task, description=f"Loaded {len(skills):,} skills")

    console.print(f"\n[green]✓[/green] Found [bold]{len(skills):,}[/bold] skills in CSV")

    skills_with_alts = sum(1 for s in skills if s.alternative_labels)
    total_alts = sum(len(s.alternative_labels) for s in skills)

    console.print(f"  • Skills with alternatives: [cyan]{skills_with_alts:,}[/cyan]")
    console.print(f"  • Total alternative labels: [cyan]{total_alts:,}[/cyan]")
    console.print(f"  • Potential synonym pairs: [cyan]{total_alts:,}[/cyan]")
    console.print()


@app.command("report")
def show_report(
    input_path: Annotated[
        Path,
        typer.Argument(help="Path to calibration report JSON."),
    ],
) -> None:
    """Display a previously generated calibration report."""
    print_header()

    if not input_path.is_file():
        print_error(f"Report file not found: {input_path}")
        raise typer.Exit(1)
    try:
        data = json.loads(input_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print_error(f"Invalid report: {e}")
        raise typer.Exit(1) from e

    if not isinstance(data, dict):
        print_error("Invalid report: root must be a JSON object")
        raise typer.Exit(1)

    console.print(f"[dim]Loaded report from: {input_path}[/dim]\n")

    _display_report_from_json(data)


def _load_and_generate_dataset(
    csv_path: Path,
    max_synonyms: int,
    max_distinct: int,
    seed: int,
) -> CalibrationDataset:
    """Load skills and generate calibration dataset with progress display."""
    with create_progress() as progress:
        load_task = progress.add_task("Loading skills from CSV...", total=1)

        loader = TabiyaLoader(csv_path)
        skills = loader.load()
        progress.update(load_task, completed=1, description=f"Loaded {len(skills):,} skills")

        gen_task = progress.add_task("Generating test pairs...", total=3)

        generator = PairGenerator(skills, seed=seed)

        synonyms = generator.generate_synonym_pairs(max_pairs=max_synonyms)
        progress.update(gen_task, advance=1, description=f"Generated {len(synonyms):,} synonym pairs")

        distinct = generator.generate_distinct_pairs(max_pairs=max_distinct)
        progress.update(gen_task, advance=1, description=f"Generated {len(distinct):,} distinct pairs")

        substring = generator.generate_substring_pairs(max_pairs=min(10000, max_distinct))
        progress.update(gen_task, advance=1, description="Deduplicating pairs...")

        all_distinct = _deduplicate_pairs(distinct + substring)[:max_distinct]

    dataset = CalibrationDataset(true_synonyms=synonyms, distinct_similar=all_distinct)

    print_dataset_summary(
        synonym_count=dataset.synonym_count,
        distinct_count=dataset.distinct_count,
        skill_count=len(skills),
    )

    return dataset


def _run_analysis(dataset: CalibrationDataset) -> AnalysisResults:
    """Run Jaccard similarity analysis with progress display."""
    analyzer = JaccardAnalyzer()
    results = AnalysisResults()

    total_pairs = dataset.total_pairs

    with create_progress() as progress:
        task = progress.add_task("Computing Jaccard similarities...", total=total_pairs)

        for pair in dataset.true_synonyms:
            score = analyzer.compute_similarity(pair.skill_a, pair.skill_b)
            results.synonym_scores.append(score)
            results.all_results.append(SimilarityResult(pair=pair, jaccard_score=score))
            progress.update(task, advance=1)

        for pair in dataset.distinct_similar:
            score = analyzer.compute_similarity(pair.skill_a, pair.skill_b)
            results.distinct_scores.append(score)
            results.all_results.append(SimilarityResult(pair=pair, jaccard_score=score))
            progress.update(task, advance=1)

    return results


def _generate_report(results: AnalysisResults) -> CalibrationReport:
    """Generate calibration report from analysis results."""
    analyzer = JaccardAnalyzer()
    return analyzer.generate_report(results)


def _display_results(report: CalibrationReport, *, show_examples: bool) -> None:
    """Display analysis results."""
    console.print()

    print_distribution_stats(
        "True Synonym Scores",
        report.results.synonym_stats,
        style="green",
    )
    console.print()

    print_distribution_stats(
        "Distinct-but-Similar Scores",
        report.results.distinct_stats,
        style="yellow",
    )
    console.print()

    print_threshold_analysis_table(report.threshold_analyses)

    analyzer = JaccardAnalyzer()
    zero_fp_analysis = analyzer.analyze_threshold(report.results, report.zero_fp_threshold)
    print_recommendation(report.zero_fp_threshold, zero_fp_analysis)

    if show_examples:
        print_false_positive_examples(report.false_positive_examples, 0.90)
        print_false_negative_examples(report.false_negative_examples, report.zero_fp_threshold)


def _save_report(report: CalibrationReport, output_path: Path) -> None:
    """Save calibration report to JSON file."""
    data = {
        "summary": {
            "synonym_pairs": report.results.synonym_stats.count,
            "distinct_pairs": report.results.distinct_stats.count,
            "zero_fp_threshold": report.zero_fp_threshold,
        },
        "synonym_statistics": _stats_to_dict(report.results.synonym_stats),
        "distinct_statistics": _stats_to_dict(report.results.distinct_stats),
        "threshold_analyses": [
            {
                "threshold": a.threshold,
                "true_positives": a.true_positives,
                "false_positives": a.false_positives,
                "recall": round(a.recall, 6),
                "false_positive_rate": round(a.false_positive_rate, 8),
            }
            for a in report.threshold_analyses
        ],
        "false_positive_examples": report.false_positive_examples,
        "false_negative_examples": report.false_negative_examples,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(data, temp_file, indent=2)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)
        temp_path.replace(output_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    print_report_saved(str(output_path))


def _stats_to_dict(stats: DistributionStats) -> dict[str, float | int]:
    """Convert DistributionStats to dictionary."""
    return {
        "count": stats.count,
        "min": round(stats.min_val, 6),
        "max": round(stats.max_val, 6),
        "mean": round(stats.mean, 6),
        "median": round(stats.median, 6),
        "std": round(stats.std, 6),
        "p25": round(stats.p25, 6),
        "p75": round(stats.p75, 6),
        "p90": round(stats.p90, 6),
        "p95": round(stats.p95, 6),
        "p99": round(stats.p99, 6),
    }


def _display_report_from_json(data: dict) -> None:
    """Display a report loaded from JSON."""
    summary = data.get("summary", {})

    console.print(f"[bold]Synonym pairs:[/bold] {summary.get('synonym_pairs', 0):,}")
    console.print(f"[bold]Distinct pairs:[/bold] {summary.get('distinct_pairs', 0):,}")
    console.print(f"[bold]Zero-FP threshold:[/bold] [cyan]{summary.get('zero_fp_threshold', 0):.4f}[/cyan]")
    console.print()

    if "threshold_analyses" in data:
        analyses = [
            ThresholdAnalysis(
                threshold=a["threshold"],
                true_positives=a["true_positives"],
                false_positives=a["false_positives"],
                true_negatives=0,
                false_negatives=0,
            )
            for a in data["threshold_analyses"]
        ]
        print_threshold_analysis_table(analyses)

    if "false_positive_examples" in data:
        print_false_positive_examples(data["false_positive_examples"], 0.90)


if __name__ == "__main__":
    app()

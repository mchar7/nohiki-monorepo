"""Rich display utilities for calibration CLI.

Provides beautiful, informative output using Rich library features:
- Progress bars and spinners
- Styled tables and panels
- Color-coded statistics
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.style import Style
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from calibrate_skill_thresholds.analysis import (
        DistributionStats,
        ThresholdAnalysis,
    )

console = Console(stderr=True)

THRESHOLD_HIGH = 0.95
THRESHOLD_MED = 0.90
THRESHOLD_LOW = 0.80

STYLE_SUCCESS = Style(color="green", bold=True)
STYLE_WARNING = Style(color="yellow")
STYLE_ERROR = Style(color="red", bold=True)
STYLE_DIM = Style(color="bright_black")
STYLE_HIGHLIGHT = Style(color="cyan", bold=True)

MIN_RECALL_THRESHOLD = 0.02
MAX_EXAMPLES_DISPLAY = 15


def create_progress() -> Progress:
    """Create a styled progress bar for data processing."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def create_spinner_progress() -> Progress:
    """Create a spinner-only progress indicator."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )


def print_header() -> None:
    """Print the CLI header banner."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Skill Threshold Calibration[/bold cyan]\n"
            "[dim]Empirically derive auto-canonicalization thresholds[/dim]",
            border_style="cyan",
            padding=(0, 2),
        ),
    )
    console.print()


def print_dataset_summary(synonym_count: int, distinct_count: int, skill_count: int) -> None:
    """Print summary of loaded dataset."""
    table = Table(
        title="[bold]Dataset Summary[/bold]",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Skills loaded", f"[cyan]{skill_count:,}[/cyan]")
    table.add_row("True synonym pairs", f"[green]{synonym_count:,}[/green]")
    table.add_row("Distinct-but-similar pairs", f"[yellow]{distinct_count:,}[/yellow]")
    table.add_row("Total test pairs", f"[bold]{synonym_count + distinct_count:,}[/bold]")

    console.print(table)
    console.print()


def print_distribution_stats(
    title: str,
    stats: DistributionStats,
    style: str = "cyan",
) -> None:
    """Print distribution statistics in a styled table."""
    table = Table(
        title=f"[bold {style}]{title}[/bold {style}]",
        show_header=True,
        header_style=f"bold {style}",
        border_style=style,
    )
    table.add_column("Statistic", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Count", f"{stats.count:,}")
    table.add_row("Min", f"{stats.min_val:.4f}")
    table.add_row("Max", f"[bold]{stats.max_val:.4f}[/bold]")
    table.add_row("Mean", f"{stats.mean:.4f}")
    table.add_row("Median", f"{stats.median:.4f}")
    table.add_row("Std Dev", f"{stats.std:.4f}")
    table.add_row("P25", f"{stats.p25:.4f}")
    table.add_row("P75", f"{stats.p75:.4f}")
    table.add_row("P90", f"{stats.p90:.4f}")
    table.add_row("P95", f"[bold]{stats.p95:.4f}[/bold]")
    table.add_row("P99", f"[bold]{stats.p99:.4f}[/bold]")

    console.print(table)


def print_threshold_analysis_table(analyses: list[ThresholdAnalysis]) -> None:
    """Print threshold analysis results in a table."""
    table = Table(
        title="[bold]Threshold Analysis[/bold]",
        show_header=True,
        header_style="bold magenta",
        border_style="magenta",
    )
    table.add_column("Threshold", justify="center", style="bold")
    table.add_column("True Pos", justify="right")
    table.add_column("False Pos", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("FP Rate", justify="right")
    table.add_column("Status", justify="center")

    for analysis in analyses:
        fp_style = "green" if analysis.false_positives == 0 else "red"
        recall_style = "green" if analysis.recall > MIN_RECALL_THRESHOLD else "yellow"

        if analysis.false_positives == 0 and analysis.true_positives > 0:
            status = "[green]✓ SAFE[/green]"
        elif analysis.false_positives == 0:
            status = "[yellow]○ No matches[/yellow]"
        else:
            status = f"[red]✗ {analysis.false_positives} FP[/red]"

        table.add_row(
            f"{analysis.threshold:.2f}",
            f"{analysis.true_positives:,}",
            f"[{fp_style}]{analysis.false_positives:,}[/{fp_style}]",
            f"[{recall_style}]{analysis.recall:.4f}[/{recall_style}]",
            f"{analysis.false_positive_rate:.6f}",
            status,
        )

    console.print(table)
    console.print()


def print_recommendation(zero_fp_threshold: float, analysis: ThresholdAnalysis) -> None:
    """Print the recommended threshold with explanation."""
    content = Text()
    content.append("Recommended Jaccard Threshold: ", style="bold")
    content.append(f"{zero_fp_threshold:.4f}\n\n", style=STYLE_HIGHLIGHT)

    content.append("At this threshold:\n", style="bold")
    content.append("  • True Positives: ", style="dim")
    content.append(f"{analysis.true_positives:,}\n", style="green")
    content.append("  • False Positives: ", style="dim")
    content.append(f"{analysis.false_positives}\n", style="green" if analysis.false_positives == 0 else "red")
    content.append("  • Recall: ", style="dim")
    content.append(f"{analysis.recall:.4f}\n", style="cyan")
    content.append("  • False Positive Rate: ", style="dim")
    content.append(f"{analysis.false_positive_rate:.6f}\n\n", style="cyan")

    content.append("This threshold guarantees ", style="dim")
    content.append("ZERO false positives", style=STYLE_SUCCESS)
    content.append(" on the test set.", style="dim")

    console.print(
        Panel(
            content,
            title="[bold green]Calibration Result[/bold green]",
            border_style="green",
            padding=(1, 2),
        ),
    )
    console.print()


def print_false_positive_examples(examples: list[dict[str, object]], threshold: float) -> None:
    """Print examples of false positives."""
    if not examples:
        console.print(f"[green]✓[/green] No false positives at threshold {threshold:.2f}")
        return

    table = Table(
        title=f"[bold red]False Positive Examples (threshold {threshold:.2f})[/bold red]",
        show_header=True,
        header_style="bold red",
        border_style="red",
    )
    table.add_column("Skill A", max_width=35)
    table.add_column("Skill B", max_width=35)
    table.add_column("Score", justify="right", style="bold")

    for ex in examples[:MAX_EXAMPLES_DISPLAY]:
        table.add_row(
            str(ex["skill_a"])[:35],
            str(ex["skill_b"])[:35],
            f"{ex['score']:.4f}",
        )

    if len(examples) > MAX_EXAMPLES_DISPLAY:
        table.add_row(
            f"[dim]... and {len(examples) - MAX_EXAMPLES_DISPLAY} more[/dim]",
            "",
            "",
        )

    console.print(table)
    console.print()


def print_false_negative_examples(examples: list[dict[str, object]], threshold: float) -> None:
    """Print examples of false negatives near the threshold."""
    if not examples:
        return

    table = Table(
        title=f"[bold yellow]Near-Miss False Negatives (below {threshold:.2f})[/bold yellow]",
        show_header=True,
        header_style="bold yellow",
        border_style="yellow",
    )
    table.add_column("Skill A", max_width=35)
    table.add_column("Skill B", max_width=35)
    table.add_column("Score", justify="right", style="bold")

    for ex in examples[:10]:
        table.add_row(
            str(ex["skill_a"])[:35],
            str(ex["skill_b"])[:35],
            f"{ex['score']:.4f}",
        )

    console.print(table)
    console.print()


def print_config_snippet(threshold: float, distinct_count: int) -> None:
    """Print a config.py snippet annotated with the actual calibration sample size."""
    snippet = f"""
# In skill_graph_service/core/config.py
class NormalizationThresholds(BaseModel):
    jaccard_auto_match: float = Field(
        default={threshold:.2f},
        description="Empirically calibrated: zero false positives on {distinct_count:,} distinct pairs"
    )

"""

    console.print(
        Panel(
            f"[dim]{snippet.strip()}[/dim]",
            title="[bold cyan]Config Snippet[/bold cyan]",
            border_style="cyan",
        ),
    )
    console.print()


def print_report_saved(path: str) -> None:
    """Print confirmation that report was saved."""
    console.print(f"[green]✓[/green] Report saved to: [cyan]{path}[/cyan]")
    console.print()


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[red]✗ Error:[/red] {message}")


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]✓[/green] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]⚠[/yellow] {message}")

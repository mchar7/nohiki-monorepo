"""Prepare command for generating training pairs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

# Force adapter registration (modules register via side effects on import)
import job_embedding_finetuning.dataset_adapters.adapters  # noqa: F401
from job_embedding_finetuning.config.settings import get_settings
from job_embedding_finetuning.dataset_adapters.base import DatasetTier
from job_embedding_finetuning.dataset_adapters.registry import get_all_adapters
from job_embedding_finetuning.processing.filters import FilterConfig
from job_embedding_finetuning.processing.pair_generator import (
    GenerationStats,
    PairGeneratorConfig,
    generate_all_pairs_with_progress,
    save_pairs_arrow,
)

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
console = Console(stderr=True)


def _display_stats(stats: GenerationStats) -> None:
    """Display generation statistics with rich tables."""
    # Summary table
    summary = Table(title="Generation Summary", show_header=False, border_style="dim")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")

    summary.add_row("Datasets processed", f"[green]{stats.datasets_processed}[/green]")
    if stats.datasets_failed > 0:
        summary.add_row("Datasets failed", f"[red]{stats.datasets_failed}[/red]")
    summary.add_row("Total pairs", f"{stats.total_pairs:,}")
    summary.add_row("After filtering", f"[bold]{stats.filtered_pairs:,}[/bold]")

    console.print()
    console.print(summary)

    if stats.pairs_by_type:
        # Pairs by type table
        type_table = Table(title="Pairs by Type", border_style="dim")
        type_table.add_column("Type", style="cyan")
        type_table.add_column("Count", justify="right")
        type_table.add_column("Percentage", justify="right")

        total = sum(stats.pairs_by_type.values())
        for pair_type, count in sorted(stats.pairs_by_type.items(), key=lambda x: -x[1]):
            pct = (count / total * 100) if total > 0 else 0
            type_table.add_row(pair_type, f"{count:,}", f"{pct:.1f}%")

        console.print()
        console.print(type_table)


@app.command("pairs")
def prepare_pairs(
    output_dir: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output directory for Arrow dataset."),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", "-d", help="Directory with downloaded data."),
    ] = None,
    tiers: Annotated[
        str,
        typer.Option("--tiers", "-t", help="Comma-separated tiers: gold,core,supplementary."),
    ] = "gold,core",
    shuffle: Annotated[
        bool,
        typer.Option("--shuffle/--no-shuffle", help="Shuffle output pairs."),
    ] = True,
    seed: Annotated[
        int,
        typer.Option("--seed", help="Random seed for shuffling."),
    ] = 42,
) -> None:
    """Generate training pairs from downloaded datasets (Arrow format)."""
    settings = get_settings()
    source_dir = data_dir or settings.data_dir
    target_dir = output_dir or settings.output_dir

    # Parse tiers
    tier_map = {
        "gold": DatasetTier.GOLD,
        "core": DatasetTier.CORE,
        "supplementary": DatasetTier.SUPPLEMENTARY,
    }
    include_tiers = tuple(tier_map[t.strip().lower()] for t in tiers.split(",") if t.strip().lower() in tier_map)

    if not include_tiers:
        console.print("[red]No valid tiers specified.[/red]")
        raise typer.Exit(1)

    # Get adapters
    adapters = list(get_all_adapters(source_dir))
    console.print(f"Found {len(adapters)} registered adapters")

    # Configure generation
    config = PairGeneratorConfig(
        include_tiers=include_tiers,
        filter_config=FilterConfig(),
        shuffle_output=shuffle,
        random_seed=seed,
    )

    # Filter adapters by tier first
    filtered_adapters = [a for a in adapters if a.info.tier in include_tiers]
    console.print(f"Processing {len(filtered_adapters)} datasets from selected tiers")
    console.print()

    # Create progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        pairs, stats = generate_all_pairs_with_progress(filtered_adapters, config, progress)

    _display_stats(stats)

    if pairs:
        # Save with progress
        console.print()
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Saving pairs to disk...[/cyan]"),
            console=console,
        ) as save_progress:
            save_progress.add_task("saving", total=None)
            output_path = save_pairs_arrow(pairs, target_dir)

        console.print(
            Panel.fit(
                f"[bold green]Success![/bold green]\n[dim]Saved {len(pairs):,} pairs to {output_path}[/dim]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel.fit(
                "[bold yellow]No pairs generated[/bold yellow]\n[dim]Check dataset availability and filters[/dim]",
                border_style="yellow",
            )
        )

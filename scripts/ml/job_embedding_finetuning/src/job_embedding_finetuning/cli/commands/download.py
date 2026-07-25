"""Download command for fetching datasets."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table

from job_embedding_finetuning.config.settings import get_settings
from job_embedding_finetuning.dataset_adapters.base import DatasetTier
from job_embedding_finetuning.dataset_adapters.download import (
    DownloadError,
    check_git_lfs,
    download_dataset,
    get_tier_datasets,
)

TIER_STYLES: Final[dict[DatasetTier, str]] = {
    DatasetTier.GOLD: "yellow",
    DatasetTier.CORE: "cyan",
    DatasetTier.SUPPLEMENTARY: "dim",
}

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
console = Console(stderr=True)


@app.command("all")
def download_all(
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", "-d", help="Directory for downloaded data."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-download existing datasets."),
    ] = False,
) -> None:
    """Download all datasets from HuggingFace using git-lfs."""
    settings = get_settings()
    target_dir = data_dir or settings.data_dir

    console.print()
    console.print(
        Panel.fit(
            "[bold blue]Job Embedding Finetuning[/bold blue]\n[dim]Downloading datasets from HuggingFace[/dim]",
            border_style="blue",
        )
    )
    console.print()

    if not check_git_lfs():
        console.print(
            Panel(
                "[red]git-lfs is not installed![/red]\n\nInstall with: [cyan]git lfs install[/cyan]",
                title="Error",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    console.print(f"[dim]Target directory: {target_dir}[/dim]")
    console.print()

    # Collect all datasets
    all_datasets = []
    for tier in DatasetTier:
        datasets = get_tier_datasets(tier)
        all_datasets.extend((tier, info) for info in datasets)

    if not all_datasets:
        console.print("[yellow]No datasets found in registry.[/yellow]")
        raise typer.Exit(1)

    success_count = 0
    skip_count = 0
    fail_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading...", total=len(all_datasets))

        for tier, info in all_datasets:
            style = TIER_STYLES[tier]
            progress.update(task, description=f"[{style}]{info.name}[/{style}]")

            try:
                downloaded = download_dataset(info, target_dir, force=force)
                if downloaded:
                    success_count += 1
                else:
                    skip_count += 1
            except DownloadError, OSError, RuntimeError, subprocess.SubprocessError:
                fail_count += 1

            progress.advance(task)

    # Summary table
    console.print()
    _print_download_summary(all_datasets, target_dir, success_count, skip_count, fail_count)


def _print_download_summary(
    all_datasets: list[tuple[DatasetTier, object]],
    target_dir: Path,
    success: int,
    skipped: int,
    failed: int,
) -> None:
    """Print a summary table of download results."""
    table = Table(
        title="Download Summary",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )
    table.add_column("Result", justify="center", width=10)
    table.add_column("Count", justify="right", width=8)

    table.add_row("[green]✓ Downloaded[/green]", str(success))
    table.add_row("[yellow]○ Skipped[/yellow]", str(skipped))
    if failed > 0:
        table.add_row("[red]✗ Failed[/red]", str(failed))

    console.print(table)

    total = len(all_datasets)
    if failed == 0:
        console.print(
            Panel.fit(
                f"[bold green]Complete![/bold green]\n[dim]{total} datasets ready in {target_dir}[/dim]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel.fit(
                f"[bold yellow]Completed with errors[/bold yellow]\n[dim]{failed} of {total} datasets failed[/dim]",
                border_style="yellow",
            )
        )


@app.command("tier")
def download_by_tier(
    tier: Annotated[
        str,
        typer.Argument(help="Dataset tier: gold, core, or supplementary."),
    ],
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", "-d", help="Directory for downloaded data."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-download existing datasets."),
    ] = False,
) -> None:
    """Download datasets by tier (gold, core, supplementary)."""
    settings = get_settings()
    target_dir = data_dir or settings.data_dir

    tier_map = {
        "gold": DatasetTier.GOLD,
        "core": DatasetTier.CORE,
        "supplementary": DatasetTier.SUPPLEMENTARY,
    }

    if tier.lower() not in tier_map:
        console.print(
            Panel(
                f"[red]Invalid tier: {tier}[/red]\n\n"
                "Valid options: [cyan]gold[/cyan], [cyan]core[/cyan], [cyan]supplementary[/cyan]",
                title="Error",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    dataset_tier = tier_map[tier.lower()]
    style = TIER_STYLES[dataset_tier]

    console.print()
    console.rule(f"[bold {style}]{tier.upper()} Tier Datasets[/bold {style}]", style=style)
    console.print()

    datasets = get_tier_datasets(dataset_tier)

    if not datasets:
        console.print(f"[yellow]No {tier} datasets found.[/yellow]")
        return

    success = 0
    for info in datasets:
        try:
            downloaded = download_dataset(info, target_dir, force=force)
            if downloaded:
                console.print(f"  [green]✓[/green] [{style}]{info.name}[/{style}]")
            else:
                console.print(f"  [yellow]○[/yellow] [{style}]{info.name}[/{style}] (exists)")
            success += 1
        except (DownloadError, OSError, RuntimeError, subprocess.SubprocessError) as e:
            console.print(f"  [red]✗[/red] [{style}]{info.name}[/{style}]: {e}")

    console.print()
    console.print(f"[green]✓ {success}/{len(datasets)} datasets ready[/green]")

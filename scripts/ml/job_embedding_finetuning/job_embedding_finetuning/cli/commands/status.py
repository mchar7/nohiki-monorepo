"""Status command for checking dataset and training status."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from job_embedding_finetuning.config.settings import get_settings
from job_embedding_finetuning.dataset_adapters.base import DatasetTier
from job_embedding_finetuning.dataset_adapters.download import get_download_status, get_tier_datasets

TIER_LABELS: Final[dict[DatasetTier, tuple[str, str]]] = {
    DatasetTier.GOLD: ("GOLD", "yellow"),
    DatasetTier.CORE: ("CORE", "cyan"),
    DatasetTier.SUPPLEMENTARY: ("SUPPLEMENTARY", "dim"),
}

DESC_TRUNCATE_LEN: Final[int] = 50
PCT_COMPLETE: Final[int] = 100
PCT_PARTIAL: Final[int] = 50
CHECKPOINT_DISPLAY_LIMIT: Final[int] = 3

app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")
console = Console(stderr=True)


@app.command("datasets")
def show_dataset_status(
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", "-d", help="Directory with downloaded data."),
    ] = None,
) -> None:
    """Show status of downloaded datasets with detailed breakdown."""
    settings = get_settings()
    source_dir = data_dir or settings.data_dir

    console.print()
    console.print(
        Panel.fit(
            f"[bold blue]Dataset Status[/bold blue]\n[dim]Data directory: {source_dir}[/dim]",
            border_style="blue",
        )
    )
    console.print()

    # Import adapters to populate registry

    total_downloaded = 0
    total_datasets = 0
    total_rows = 0

    for tier in DatasetTier:
        datasets = get_tier_datasets(tier)
        if not datasets:
            continue

        label, style = TIER_LABELS[tier]
        status = get_download_status(source_dir, datasets)

        downloaded = sum(1 for d in datasets if status.get(d.name, False))
        total_downloaded += downloaded
        total_datasets += len(datasets)

        table = Table(
            title=f"[bold {style}]{label} Tier[/bold {style}] ({downloaded}/{len(datasets)})",
            show_header=True,
            header_style=f"bold {style}",
            border_style=style,
            expand=True,
        )
        table.add_column("Dataset", ratio=2)
        table.add_column("Status", justify="center", width=10)
        table.add_column("Rows", justify="right", width=12)
        table.add_column("Description", ratio=3)

        for info in datasets:
            is_downloaded = status.get(info.name, False)
            if is_downloaded:
                status_icon = "[green]✓ Ready[/green]"
                total_rows += info.estimated_rows or 0
            else:
                status_icon = "[red]✗ Missing[/red]"

            rows_str = f"{info.estimated_rows:,}" if info.estimated_rows else "-"
            desc = _truncate(info.description, DESC_TRUNCATE_LEN)
            table.add_row(info.name, status_icon, rows_str, f"[dim]{desc}[/dim]")

        console.print(table)
        console.print()

    # Summary
    pct = (total_downloaded / total_datasets * 100) if total_datasets > 0 else 0
    summary_style = _get_progress_style(pct)
    console.print(
        Panel.fit(
            f"[bold {summary_style}]{total_downloaded}/{total_datasets} "
            f"datasets ready ({pct:.0f}%)[/bold {summary_style}]\n"
            f"[dim]~{total_rows:,} total rows available[/dim]",
            border_style=summary_style,
        )
    )


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    return text[:max_len] + "..." if len(text) > max_len else text


def _get_progress_style(pct: float) -> str:
    """Get style based on completion percentage."""
    if pct >= PCT_COMPLETE:
        return "green"
    if pct >= PCT_PARTIAL:
        return "yellow"
    return "red"


@app.command("training")
def show_training_status(
    output_dir: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output directory."),
    ] = None,
) -> None:
    """Show status of training outputs and artifacts."""
    settings = get_settings()
    target_dir = output_dir or settings.output_dir

    console.print()
    console.print(
        Panel.fit(
            f"[bold blue]Training Status[/bold blue]\n[dim]Output directory: {target_dir}[/dim]",
            border_style="blue",
        )
    )
    console.print()

    # Build and display status tree
    tree = Tree("[bold]Training Pipeline[/bold]", guide_style="dim")
    has_pairs = _add_pairs_status(tree, target_dir)
    has_model = _add_model_status(tree, target_dir)
    _add_checkpoint_status(tree, target_dir)

    console.print(tree)
    console.print()
    _print_overall_status(has_pairs=has_pairs, has_model=has_model)


def _add_pairs_status(tree: Tree, target_dir: Path) -> bool:
    """Add training pairs status to tree."""
    pairs_branch = tree.add("[cyan]Training Data[/cyan]")
    pairs_jsonl = target_dir / "training_pairs.jsonl"
    pairs_json = target_dir / "training_pairs.json"

    if pairs_jsonl.exists():
        line_count = sum(1 for _ in pairs_jsonl.open())
        size_mb = pairs_jsonl.stat().st_size / (1024 * 1024)
        pairs_branch.add(f"[green]✓[/green] {pairs_jsonl.name} ({line_count:,} pairs, {size_mb:.1f} MB)")
        return True
    if pairs_json.exists():
        size_mb = pairs_json.stat().st_size / (1024 * 1024)
        pairs_branch.add(f"[green]✓[/green] {pairs_json.name} ({size_mb:.1f} MB)")
        return True
    pairs_branch.add("[red]✗[/red] No training pairs (run [cyan]prepare pairs[/cyan])")
    return False


def _add_model_status(tree: Tree, target_dir: Path) -> bool:
    """Add model status to tree."""
    model_branch = tree.add("[cyan]Model[/cyan]")
    model_dir = target_dir / "model" / "final_model"
    if model_dir.exists():
        model_branch.add(f"[green]✓[/green] Final model: {model_dir.name}")
        return True
    model_branch.add("[red]✗[/red] No trained model (run [cyan]train run[/cyan])")
    return False


def _add_checkpoint_status(tree: Tree, target_dir: Path) -> None:
    """Add checkpoint status to tree."""
    checkpoint_branch = tree.add("[cyan]Checkpoints[/cyan]")
    model_parent = target_dir / "model"
    if not model_parent.exists():
        checkpoint_branch.add("[dim]○[/dim] No model directory")
        return

    checkpoints = sorted(model_parent.glob("checkpoint-*"))
    if not checkpoints:
        checkpoint_branch.add("[yellow]○[/yellow] No checkpoints yet")
        return

    for cp in checkpoints[-CHECKPOINT_DISPLAY_LIMIT:]:
        checkpoint_branch.add(f"[green]✓[/green] {cp.name}")
    if len(checkpoints) > CHECKPOINT_DISPLAY_LIMIT:
        extra = len(checkpoints) - CHECKPOINT_DISPLAY_LIMIT
        checkpoint_branch.add(f"[dim]... and {extra} more[/dim]")


def _print_overall_status(*, has_pairs: bool, has_model: bool) -> None:
    """Print overall pipeline status."""
    if has_model:
        console.print(
            Panel.fit(
                "[bold green]Ready for inference![/bold green]\n[dim]Model trained and available[/dim]",
                border_style="green",
            )
        )
    elif has_pairs:
        console.print(
            Panel.fit(
                "[bold yellow]Ready for training[/bold yellow]\n[dim]Run: job-embedding-finetune train run[/dim]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel.fit(
                "[bold red]Setup required[/bold red]\n[dim]1. download all  2. prepare pairs  3. train run[/dim]",
                border_style="red",
            )
        )

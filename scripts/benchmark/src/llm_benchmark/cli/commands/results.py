"""CLI command for displaying saved benchmark results."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from llm_benchmark.cli._helpers import find_latest_result, load_benchmark_result
from llm_benchmark.display.console import console
from llm_benchmark.display.panels import display_benchmark_results


def results(
    result_file: Annotated[Path | None, typer.Argument(help="Benchmark result JSON file (default: latest)")] = None,
) -> None:
    """Display results from a saved benchmark JSON file."""
    if result_file is None:
        if latest := find_latest_result():
            result_file = latest
        else:
            console.print("[red]Error:[/red] No benchmark results found.")
            raise typer.Exit(code=1)

    if not result_file.exists():
        console.print(f"[red]Error:[/red] Result file not found: {result_file}")
        raise typer.Exit(code=1)

    benchmark = load_benchmark_result(result_file)
    console.print(f"[dim]Loaded: {result_file}[/dim]\n")
    display_benchmark_results(benchmark)

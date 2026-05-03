"""Progress bar factory functions for benchmark and evaluation.

Provides pre-configured Rich Progress instances for consistent progress
display across CLI commands.
"""

from __future__ import annotations

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from llm_benchmark.display.console import console

__all__ = [
    "create_benchmark_progress",
    "create_evaluation_progress",
]


def create_benchmark_progress() -> Progress:
    """Create a progress bar for benchmark run execution.

    Returns:
        A configured Rich Progress instance with spinner, bar, and timing.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=False,
    )


def create_evaluation_progress() -> Progress:
    """Create a progress bar for judge evaluation.

    Returns:
        A configured Rich Progress instance with spinner, bar, and timing.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=False,
    )

"""Generic parallel package scanner with live TUI or CI output.

Replaces the duplicated scan_parallel() function that existed verbatim
across deadcode_check, deptry_check, and fixture_check. Uses asyncio.TaskGroup
instead of asyncio.gather to catch unhandled task exceptions eagerly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

if TYPE_CHECKING:
    from ci_checks.core.packages import Package


class _ResultLike(Protocol):
    name: str
    passed: bool
    duration_ms: int


def _build_progress(console: Console) -> Progress:
    """Build the standard Rich progress bar for interactive mode."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=True,
    )


async def scan_parallel[R: _ResultLike](
    packages: list[Package],
    scan_fn: Callable[[Package], Awaitable[R]],
    max_workers: int,
    console: Console,
    *,
    ci_mode: bool,
    ci_suffix: Callable[[R], str] | None = None,
) -> list[R]:
    """Scan packages in parallel, with CI plain-text or interactive TUI output.

    Uses asyncio.TaskGroup so unhandled exceptions surface immediately rather
    than being silently swallowed. Individual scan functions are expected to
    catch their own errors and return them via the result's error field.

    Args:
        packages: Packages to scan.
        scan_fn: Async function that runs the check on a single package.
        max_workers: Maximum number of concurrent scan processes.
        console: Rich console for output.
        ci_mode: If True, use plain-text output; otherwise render a live TUI.
        ci_suffix: Optional callback producing extra suffix text per result
            in CI mode (e.g., " (3 findings)" for deadcode).

    Returns:
        List of scan results in the same order as the input packages.
    """
    semaphore = asyncio.Semaphore(max_workers)
    results: list[R | None] = [None] * len(packages)
    pkg_index = {pkg.name: i for i, pkg in enumerate(packages)}

    if ci_mode:
        return await _scan_ci(packages, scan_fn, semaphore, console, ci_suffix, results, pkg_index)
    return await _scan_interactive(packages, scan_fn, semaphore, console, results, pkg_index)


async def _scan_ci[R: _ResultLike](
    packages: list[Package],
    scan_fn: Callable[[Package], Awaitable[R]],
    semaphore: asyncio.Semaphore,
    console: Console,
    ci_suffix: Callable[[R], str] | None,
    results: list[R | None],
    pkg_index: dict[str, int],
) -> list[R]:
    """Run scans in CI mode with simple one-line-per-package output."""

    async def run(pkg: Package) -> None:
        async with semaphore:
            result = await scan_fn(pkg)
            icon = "✓" if result.passed else "✗"
            suffix = ci_suffix(result) if ci_suffix else ""
            console.print(f"{icon} {result.name} ({result.duration_ms}ms){suffix}")
            results[pkg_index[pkg.name]] = result

    async with asyncio.TaskGroup() as tg:
        for pkg in packages:
            tg.create_task(run(pkg))

    # All tasks completed; results list is fully populated.
    return [r for r in results if r is not None]


async def _scan_interactive[R: _ResultLike](
    packages: list[Package],
    scan_fn: Callable[[Package], Awaitable[R]],
    semaphore: asyncio.Semaphore,
    console: Console,
    results: list[R | None],
    pkg_index: dict[str, int],
) -> list[R]:
    """Run scans with a live Rich TUI progress display."""
    progress = _build_progress(console)
    task_ids: dict[str, TaskID] = {}

    async def run(pkg: Package) -> None:
        task_id = task_ids[pkg.name]
        async with semaphore:
            progress.update(task_id, description=f"[blue]🔍 {pkg.name}", completed=10)
            result = await scan_fn(pkg)
            color = "green" if result.passed else "red"
            icon = "✓" if result.passed else "✗"
            progress.update(task_id, description=f"[{color}]{icon} {pkg.name}", completed=100)
            results[pkg_index[pkg.name]] = result

    with Live(progress, console=console, refresh_per_second=10):
        for pkg in packages:
            task_ids[pkg.name] = progress.add_task(f"[cyan]{pkg.name}", total=100)

        async with asyncio.TaskGroup() as tg:
            for pkg in packages:
                tg.create_task(run(pkg))

    return [r for r in results if r is not None]

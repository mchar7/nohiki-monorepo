"""Rich TUI components for health-check output: tables, panels, progress, summary."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.align import Align
from rich.box import HEAVY, ROUNDED
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from health_check.cli.formatting import (
    format_duration,
    plain_status_icon,
    status_icon,
    status_style,
    truncate,
)
from health_check.core.models import CheckCategory

if TYPE_CHECKING:
    from health_check.core.models import CheckResult, CheckSuiteResult


def _header_panel() -> Panel:
    """Create the Nohiki Health Check header panel."""
    content = Group(
        Text("NOHIKI", style="bold cyan"),
        Text("Service Health Check", style="italic dim"),
    )
    return Panel(content, box=ROUNDED, style="on #1a1a2e", padding=(1, 4))


def _results_table(results: list[CheckResult], *, verbose: bool = False) -> Table:
    """Build a grouped results table sorted by category."""
    table = Table(
        title="[bold]Health Check Results[/bold]",
        show_header=True,
        header_style="bold #00d4ff",
        style="dim",
        box=ROUNDED,
        border_style="#4a5568",
        expand=False,
    )
    table.add_column("", width=3)
    table.add_column("Check", style="cyan", min_width=28)
    table.add_column("Summary", min_width=36)
    table.add_column("Duration", justify="right", width=9)

    by_category: defaultdict[CheckCategory, list[CheckResult]] = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    for category in CheckCategory:
        category_results = by_category.get(category)
        if not category_results:
            continue
        table.add_row("", f"[bold dim]{category.value.upper()}[/bold dim]", "", "")
        for r in category_results:
            icon = status_icon(r.status)
            style = status_style(r.status)
            duration = format_duration(r.duration_ms) if r.duration_ms else ""
            table.add_row(
                icon,
                f"[{style}]{r.name}[/{style}]",
                f"[{style}]{truncate(r.summary)}[/{style}]",
                f"[dim]{duration}[/dim]",
            )
            if verbose:
                for detail in r.details:
                    table.add_row("", "", f"  [dim]↳ {truncate(detail, 80)}[/dim]", "")

    return table


def _issues_panel(results: list[CheckResult]) -> Panel | None:
    """Build an issues panel showing failures and errors, or None if all passed."""
    issues = [r for r in results if r.failed]
    if not issues:
        return None

    lines: list[str] = []
    for r in issues:
        lines.append(f"[bold red]{escape(r.name)}[/bold red]: {escape(r.summary)}")
        lines.extend(f"  • {escape(d)}" for d in r.details)
        if r.remediation_hint:
            lines.append(f"  [dim]→ {escape(r.remediation_hint)}[/dim]")
        if r.error:
            lines.append(f"  [dim red]Error: {escape(r.error[:300])}[/dim red]")
        lines.append("")

    return Panel(
        Text.from_markup("\n".join(lines)),
        title="[bold red]✗ Issues Detected[/bold red]",
        border_style="red",
        box=HEAVY,
        padding=(1, 2),
    )


def _remediation_panel(suite: CheckSuiteResult) -> Panel | None:
    """Render immutable before/action/after remediation evidence."""
    if not suite.remediations:
        return None
    lines: list[str] = []
    for record in suite.remediations:
        lines.extend(
            (
                f"[bold]{escape(record.check_id)}[/bold]",
                f"  BEFORE  {record.before.status.value}: {escape(record.before.summary)}",
                (
                    f"  ACTION  {record.action.action_id or '-'} {record.action.status.value}: "
                    f"{escape(record.action.summary)} ({format_duration(record.action.duration_ms)})"
                ),
                f"  AFTER   {record.after.status.value}: {escape(record.after.summary)}",
            )
        )
        lines.extend(f"    {escape(detail)}" for detail in record.action.details)
        if record.action.error:
            lines.append(f"    Error: {escape(record.action.error[:300])}")
    return Panel(Text.from_markup("\n".join(lines)), title="[bold]Remediation Audit[/bold]", box=ROUNDED)


def _summary_banner(suite: CheckSuiteResult) -> Panel:
    """Build a summary banner showing overall pass/fail status."""
    total = suite.total_count
    if not suite.complete:
        headline = Text("! INCOMPLETE COVERAGE", style="bold yellow")
        icon = "!"
        detail = (
            f"{suite.passed_count}/{total} passed, {len(suite.unexercised_ids)} unexercised: "
            f"{', '.join(suite.unexercised_ids)}"
        )
        border = "yellow"
    elif suite.passed:
        headline = Text("✓ ALL SYSTEMS OPERATIONAL", style="bold green")
        icon, detail, border = "🟢", f"All {total} checks passed", "green"
    else:
        headline = Text("✗ ISSUES DETECTED", style="bold red")
        icon = "🔴"
        detail = f"{suite.passed_count}/{total} passed, {suite.failed_count} failed"
        border = "red"

    content = Group(
        Align.center(headline),
        "",
        Text(f"{detail} -- {format_duration(suite.total_duration_ms)}", justify="center", style="dim"),
    )
    return Panel(content, title=f" {icon} Summary ", border_style=border, box=ROUNDED, padding=(1, 4))


def display_suite_results(
    suite: CheckSuiteResult,
    console: Console,
    *,
    verbose: bool = False,
) -> None:
    """Render a full health-check suite result to the console.

    Args:
        suite: Completed check suite result.
        console: Rich console to render to.
        verbose: If True, include per-check detail lines in the table.
    """
    console.print()
    console.print(_header_panel())
    console.print()
    console.print(_results_table(list(suite.results), verbose=verbose))
    console.print()

    if panel := _issues_panel(list(suite.results)):
        console.print(panel)
        console.print()

    if panel := _remediation_panel(suite):
        console.print(panel)
        console.print()
    console.print(_summary_banner(suite))
    console.print()


def _result_json(result: CheckResult) -> dict[str, object]:
    """Serialize one check phase without secrets or platform internals."""
    return {
        "status": result.status.value,
        "summary": result.summary,
        "details": list(result.details),
        "error": result.error,
        "duration_ms": round(result.duration_ms, 1),
    }


def display_json(suite: CheckSuiteResult, console: Console) -> None:
    """Render results as formatted JSON for CI/scripting consumption.

    Args:
        suite: Completed check suite result.
        console: Rich console to render to.
    """
    data = {
        "passed": suite.passed,
        "complete": suite.complete,
        "platform": suite.platform.value,
        "total_duration_ms": round(suite.total_duration_ms, 1),
        "summary": {
            "passed": suite.passed_count,
            "failed": suite.failed_count,
            "skipped": suite.skipped_count,
            "unexercised": len(suite.unexercised_ids),
            "total": suite.total_count,
        },
        "unexercised_ids": list(suite.unexercised_ids),
        "results": [
            {
                "id": r.check_id,
                "name": r.name,
                "category": r.category.value,
                "status": r.status.value,
                "summary": r.summary,
                "details": list(r.details),
                "error": r.error,
                "remediation_hint": r.remediation_hint,
                "duration_ms": round(r.duration_ms, 1),
            }
            for r in suite.results
        ],
        "remediations": [
            {
                "check_id": record.check_id,
                "before": _result_json(record.before),
                "action": {
                    "id": record.action.action_id,
                    "status": record.action.status.value,
                    "summary": record.action.summary,
                    "details": list(record.action.details),
                    "error": record.action.error,
                    "duration_ms": round(record.action.duration_ms, 1),
                },
                "after": _result_json(record.after),
            }
            for record in suite.remediations
        ],
    }
    console.print(Syntax(json.dumps(data, indent=2), "json", theme="monokai"))


def make_progress_bar(console: Console) -> Progress:
    """Create a Rich progress bar for live check execution display.

    Args:
        console: Rich console to attach the progress bar to.

    Returns:
        Configured ``Progress`` instance (not yet started).
    """
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(complete_style="green", finished_style="bright_green"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def display_suite_results_boring(
    suite: CheckSuiteResult,
    *,
    verbose: bool = False,
) -> None:
    """Render a health-check suite result as plain, token-efficient text.

    Outputs the same information as ``display_suite_results`` but with no
    Rich markup, no box-drawing characters, and minimal whitespace -- optimised
    for CI logs, programmatic consumption, and ``--no-color`` environments.

    Args:
        suite: Completed check suite result.
        verbose: If True, include per-check detail lines.
    """
    con = Console(no_color=True, markup=False, highlight=False, soft_wrap=True)
    con.print(f"=== NOHIKI HEALTH CHECK ({suite.platform}) ===")
    con.print()

    current_category = ""
    for r in suite.results:
        if r.category.value != current_category:
            current_category = r.category.value
            con.print(f"[{current_category.upper()}]")
        duration = f" ({format_duration(r.duration_ms)})" if r.duration_ms else ""
        con.print(f"  {plain_status_icon(r.status)}  {r.name}{duration}: {r.summary}")
        if verbose or r.failed:
            for d in r.details:
                con.print(f"    - {d}")
            if r.remediation_hint:
                con.print(f"    Hint: {r.remediation_hint}")
            if r.error:
                con.print(f"    Error: {r.error[:400]}")

    if suite.remediations:
        con.print()
        con.print("[REMEDIATIONS]")
        for record in suite.remediations:
            con.print(f"  {record.check_id}")
            con.print(f"    BEFORE: {record.before.status.value}: {record.before.summary}")
            con.print(
                f"    ACTION: {record.action.action_id or '-'} {record.action.status.value}: {record.action.summary}"
            )
            for detail in record.action.details:
                con.print(f"      - {detail}")
            if record.action.error:
                con.print(f"      Error: {record.action.error[:400]}")
            con.print(f"    AFTER: {record.after.status.value}: {record.after.summary}")
    con.print()
    total = suite.total_count
    if not suite.complete:
        status_line = (
            f"INCOMPLETE: {suite.passed_count}/{total} passed, {suite.failed_count} failed, "
            f"{suite.skipped_count} skipped, {len(suite.unexercised_ids)} unexercised "
            f"({', '.join(suite.unexercised_ids)})"
        )
    elif suite.passed:
        status_line = f"ALL PASSED ({total}/{total})"
    else:
        status_line = f"{suite.passed_count}/{total} passed, {suite.failed_count} failed" + (
            f", {suite.skipped_count} skipped" if suite.skipped_count else ""
        )
    con.print(f"SUMMARY: {status_line} - {format_duration(suite.total_duration_ms)}")


def make_live_callback(
    progress: Progress,
    task_id: TaskID,
    on_complete: Callable[[CheckResult], None] | None = None,
) -> Callable[[CheckResult], None]:
    """Build an on_check_complete callback that advances the progress bar.

    Args:
        progress: Active Rich progress bar.
        task_id: The progress task to advance.
        on_complete: Optional additional callback to invoke after advancing.

    Returns:
        Callback function compatible with ``CheckRunner``.
    """

    def _callback(result: CheckResult) -> None:
        progress.update(task_id, description=f"[cyan]{result.name}... {status_icon(result.status)}")
        progress.advance(task_id)
        if on_complete is not None:
            on_complete(result)

    return _callback

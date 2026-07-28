"""Shared Rich display utilities and console singleton for CI checks.

CI scripts output to stdout (not stderr) so their logs are captured by
CI systems as regular output, matching conventional CI tool behaviour.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

LANE_DISPLAY_NAMES: dict[str, str] = {
    "nix": "Nix toolchain",
    "lint_python": "Python lint",
    "lint_frontend": "Frontend lint",
    "lint_steiger": "Frontend architecture lint",
    "lint_proto": "Protobuf lint",
    "lint_markdown": "Markdown lint",
    "lint_workflows": "Workflow lint",
    "lint_docker": "Dockerfile lint",
    "typecheck_backend": "Backend typecheck",
    "build_backend": "Build backend",
    "typecheck_frontend": "Frontend typecheck",
    "python_any": "Python tests",
    "frontend_tests": "Frontend tests",
    "frontend_smoke": "Frontend container smoke",
    "frontend_e2e": "Playwright runner smoke",
    "node_workspace_contracts": "Node workspace contracts",
    "edge_worker": "Edge worker quality",
    "otel_collector": "OpenTelemetry collector validation",
    "hygiene": "Code hygiene",
    "api_schema_freshness": "API schema freshness",
    "image_matrix_parity": "Image matrix parity",
    "proto_breaking": "Protobuf compatibility",
}

# Where each lane executes on a broad run. A standard run collapses every selected lane onto the
# single `all` unit, so this names the broad-class bin only. It lives beside the display names
# because the step summary is its only consumer; `test_change_gate_workflow` asserts it against the
# workflow's own binning, so a rebin cannot silently make the summary lie.
LANE_RUNNERS: dict[str, str] = {
    "nix": "hygiene",
    "lint_python": "hygiene",
    "lint_frontend": "frontend",
    "lint_steiger": "frontend",
    "lint_proto": "hygiene",
    "lint_markdown": "frontend",
    "lint_workflows": "hygiene",
    "lint_docker": "hygiene",
    "typecheck_backend": "hygiene",
    "build_backend": "hygiene",
    "typecheck_frontend": "frontend",
    "python_any": "python",
    "frontend_tests": "frontend",
    "frontend_smoke": "Container contracts",
    "frontend_e2e": "Playwright runner image",
    "node_workspace_contracts": "hygiene",
    "edge_worker": "frontend",
    "otel_collector": "Container contracts",
    "hygiene": "hygiene",
    "api_schema_freshness": "hygiene",
    "image_matrix_parity": "hygiene",
    "proto_breaking": "hygiene",
}

type ColumnAlign = Literal["left", "center", "right"]

_ALIGN_RULES: dict[ColumnAlign, str] = {"left": "---", "center": ":---:", "right": "---:"}

# Module-level console singleton for all CI check output.
# stdout (not stderr) is intentional -- CI log capture expects stdout.
console = Console()


def render_summary_table(
    title: str,
    clean_count: int,
    failed_count: int,
    total_issues: int,
    extra_rows: list[tuple[str, str]] | None = None,
) -> None:
    """Render a two-column summary table to the console.

    Args:
        title: Table title displayed above the table.
        clean_count: Number of packages that passed.
        failed_count: Number of packages with findings.
        total_issues: Total issue count across all packages.
        extra_rows: Optional additional rows as (label, value) tuples.
    """
    table = Table(title=title, show_header=False)
    table.add_row("[green]Clean packages[/green]", str(clean_count))
    table.add_row("[red]Packages with issues[/red]", str(failed_count))
    table.add_row("[bold]Total issues[/bold]", str(total_issues))
    for label, value in extra_rows or []:
        table.add_row(label, value)
    console.print(table)


def render_error_panel(name: str, content: str, *, border_style: str = "red") -> None:
    """Render a bordered panel showing per-package error details.

    Args:
        name: Package name shown in the panel title.
        content: Body text displayed inside the panel.
        border_style: Rich style for the panel border colour.
    """
    console.print(
        Panel(
            content,
            title=f"[{border_style}]{name}[/{border_style}]",
            border_style=border_style,
        )
    )


def markdown_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    align: Sequence[ColumnAlign] | None = None,
) -> list[str]:
    """Render a GitHub-flavoured Markdown table as step-summary lines.

    Args:
        headers: Column headings.
        rows: One sequence of cell values per row, each as wide as ``headers``.
        align: Per-column alignment; defaults to left for every column.

    Returns:
        Header, rule and body lines, ready to join with newlines.
    """
    alignment: list[ColumnAlign] = list(align) if align else ["left"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(_ALIGN_RULES[value] for value in alignment) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def markdown_details(summary: str, body: str) -> list[str]:
    """Render a collapsed disclosure block as step-summary lines.

    Args:
        summary: Text shown on the closed disclosure control.
        body: Markdown revealed when the block is expanded.

    Returns:
        Lines for the disclosure block, ready to join with newlines.
    """
    return [f"<details><summary>{summary}</summary>", "", body, "", "</details>"]

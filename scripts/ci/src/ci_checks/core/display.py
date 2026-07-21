"""Shared Rich display utilities and console singleton for CI checks.

CI scripts output to stdout (not stderr) so their logs are captured by
CI systems as regular output, matching conventional CI tool behaviour.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

LANE_DISPLAY_NAMES: dict[str, str] = {
    "nix": "Nix toolchain",
    "lint_python": "Python lint",
    "lint_frontend": "Frontend lint",
    "lint_proto": "Protobuf lint",
    "lint_markdown": "Markdown lint",
    "lint_workflows": "Workflow lint",
    "lint_docker": "Dockerfile lint",
    "typecheck_backend": "Backend typecheck",
    "typecheck_frontend": "Frontend typecheck",
    "python_any": "Python tests",
    "frontend_tests": "Frontend tests",
    "frontend_smoke": "Frontend container smoke",
    "frontend_e2e": "Playwright runner smoke",
    "edge_worker": "Edge worker quality",
    "otel_collector": "OpenTelemetry collector validation",
    "hygiene": "Code hygiene",
    "api_schema_freshness": "API schema freshness",
    "image_matrix_parity": "Image matrix parity",
    "proto_breaking": "Protobuf compatibility",
}

GATE_LABELS: dict[str, tuple[str, str]] = {
    "python_any": ("area:backend", "1D76DB"),
    "frontend_tests": ("area:frontend", "D4C5F9"),
    "lint_proto": ("area:proto", "FBCA04"),
    "lint_docker": ("area:docker", "0E8A16"),
    "lint_workflows": ("area:workflows", "5319E7"),
    "lint_markdown": ("area:docs", "0075CA"),
    "full": ("ci:full-run", "B60205"),
}

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

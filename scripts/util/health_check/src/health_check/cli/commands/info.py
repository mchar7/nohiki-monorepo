"""``health-check info`` command: show detailed info for a single check."""

from __future__ import annotations

import typer
from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from health_check.core.registry import CheckRegistry


def info_command(
    check_id: str = typer.Argument(help="Check ID to inspect (use 'list' to see all)"),
) -> None:
    """Show detailed metadata for a specific health check."""
    console = Console()
    registry = CheckRegistry()
    registry.discover()

    check = registry.get_check(check_id)
    if check is None:
        console.print(f"[red]Check not found: {check_id!r}[/red]")
        console.print("[dim]Run [bold]health-check list[/bold] to see all available checks.[/dim]")
        raise typer.Exit(1)

    meta = check.metadata
    table = Table(box=ROUNDED, show_header=False, expand=False)
    table.add_column("Field", style="bold cyan", width=20)
    table.add_column("Value")

    platforms_str = ", ".join(p.value for p in sorted(meta.platforms, key=lambda p: p.value))
    depends_str = ", ".join(sorted(meta.depends_on)) if meta.depends_on else "none"

    rows = [
        ("ID", meta.check_id),
        ("Name", meta.name),
        ("Category", meta.category.value),
        ("Description", meta.description or "--"),
        ("Platforms", platforms_str),
        ("Depends On", depends_str),
        ("Timeout", f"{meta.timeout_seconds:.0f}s"),
        ("Supports Fix", "yes" if check.supports_fix else "no"),
    ]
    for field, value in rows:
        table.add_row(field, value)

    panel = Panel(
        table,
        title=f"[bold cyan]{meta.name}[/bold cyan]",
        box=ROUNDED,
        expand=False,
    )
    console.print()
    console.print(panel)
    console.print()

"""``health-check list`` command: list all registered checks with metadata."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.box import ROUNDED
from rich.console import Console
from rich.table import Table

from health_check.cli.formatting import status_style
from health_check.core.models import CheckCategory, CheckStatus
from health_check.core.registry import CheckRegistry
from health_check.platform.models import PlatformTarget


def list_command(
    category: Annotated[
        str | None,
        typer.Option("--category", "-c", help="Filter by category"),
    ] = None,
    platform: Annotated[
        str | None,
        typer.Option("--platform", "-p", help="Filter by platform: compose, k8s, kubernetes"),
    ] = None,
) -> None:
    """List all registered health checks with metadata.

    Args:
        category: Optional check category filter.
        platform: Optional platform filter: ``compose``, ``k8s``, or ``kubernetes``.

    Returns:
        None.
    """
    console = Console()
    registry = CheckRegistry()
    registry.discover()

    resolved_category: frozenset[CheckCategory] | None = None
    if category:
        try:
            resolved_category = frozenset({CheckCategory(category)})
        except ValueError as exc:
            console.print(f"[red]Unknown category: {category!r}[/red]")
            raise typer.Exit(1) from exc

    resolved_platform: PlatformTarget | None = None
    if platform:
        try:
            platform_value = "kubernetes" if platform.lower() == "k8s" else platform.lower()
            resolved_platform = PlatformTarget(platform_value)
        except ValueError as exc:
            console.print(f"[red]Unknown platform: {platform!r}[/red]")
            raise typer.Exit(1) from exc

    checks = registry.get_checks(
        platform=resolved_platform,
        categories=resolved_category,
    )

    if not checks:
        console.print("[yellow]No checks match the given filters.[/yellow]")
        return

    table = Table(
        title=f"[bold]Health Checks[/bold] ({len(checks)} total)",
        box=ROUNDED,
        header_style="bold #00d4ff",
        show_header=True,
        expand=False,
    )
    table.add_column("ID", style="cyan", min_width=30)
    table.add_column("Name", min_width=28)
    table.add_column("Category", style="dim", width=14)
    table.add_column("Platforms", width=18)
    table.add_column("Timeout", justify="right", width=8)
    table.add_column("Depends On", style="dim", min_width=16)

    for check in sorted(checks, key=lambda c: (c.metadata.category.value, c.metadata.check_id)):
        meta = check.metadata
        platforms_str = ", ".join(p.value for p in sorted(meta.platforms, key=lambda p: p.value))
        depends_str = ", ".join(sorted(meta.depends_on)) if meta.depends_on else "-"
        style = status_style(CheckStatus.PASSED)
        table.add_row(
            meta.check_id,
            f"[{style}]{meta.name}[/{style}]",
            meta.category.value,
            platforms_str,
            f"{meta.timeout_seconds:.0f}s",
            depends_str,
        )

    console.print(table)

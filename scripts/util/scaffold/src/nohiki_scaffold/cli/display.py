"""Rich renderers for scaffolder CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nohiki_scaffold.cli.formatting import format_lib_summary, format_service_summary
from nohiki_scaffold.core.build import BuildPlan
from nohiki_scaffold.core.models import LibSpec, ServiceSpec

console = Console()


def render_spec_panel(spec: ServiceSpec | LibSpec) -> None:
    """Print a Rich panel with a 2-column table of spec fields.

    Args:
        spec: ServiceSpec or LibSpec to render.
    """
    table = Table(show_header=False, show_edge=False)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    rows = format_service_summary(spec) if isinstance(spec, ServiceSpec) else format_lib_summary(spec)

    for label, value in rows:
        table.add_row(label, value)

    title = f"{spec.name} spec"
    panel = Panel(table, title=title, expand=False)
    console.print(panel)


def render_plan_files(plan: BuildPlan, *, explain: bool = False) -> None:
    """Print a Rich table of files to be written.

    When explain is True, include a 'Trigger' column showing each FileWrite.trigger.
    Default table: Path column only, sorted alphabetically.

    Args:
        plan: BuildPlan to render.
        explain: If True, include trigger/reason for each file.
    """
    table = Table(title="Files to be written")
    table.add_column("Path", style="cyan")
    if explain:
        table.add_column("Trigger", style="yellow")

    for fw in sorted(plan.files, key=lambda x: str(x.path)):
        if explain:
            table.add_row(str(fw.path), fw.trigger)
        else:
            table.add_row(str(fw.path))

    console.print(table)


def render_root_edits(plan: BuildPlan) -> None:
    """Print a Rich list of workspace edits (TomlEdit.description).

    Args:
        plan: BuildPlan containing root edits.
    """
    if not plan.root_edits:
        return

    console.print("\n[bold]Workspace edits:[/bold]")
    for edit in plan.root_edits:
        console.print(f"  [yellow]·[/yellow] {edit.description}")


def render_hints(plan: BuildPlan) -> None:
    """Print a Rich panel with follow-up hints (kafka topic registration, compose entries, etc.).

    Args:
        plan: BuildPlan containing hints.
    """
    if not plan.hints:
        return

    hints_text = "\n".join(plan.hints)
    panel = Panel(hints_text, title="Next steps", style="blue")
    console.print(panel)


def render_validation_errors(errors: list[str]) -> None:
    """Print validation errors as a Rich red list.

    Args:
        errors: List of error messages.
    """
    if not errors:
        return

    console.print("\n[bold red]Validation errors:[/bold red]")
    for error in errors:
        console.print(f"  [red]✗[/red] {error}")


def render_file_content_preview(plan: BuildPlan, *, max_lines: int = 30) -> None:
    """Print first N lines of each rendered file for --preview inspection.

    Used only by 'preview' command with --full flag.

    Args:
        plan: BuildPlan containing files.
        max_lines: Maximum number of lines to show per file.
    """
    console.print("\n[bold]File content preview:[/bold]")
    for fw in sorted(plan.files, key=lambda x: str(x.path)):
        lines = fw.content.split("\n")[:max_lines]
        content = "\n".join(lines)
        if len(fw.content.split("\n")) > max_lines:
            content += f"\n... ({len(fw.content.split('\n')) - max_lines} more lines)"

        title = f"{fw.path.name} ({fw.trigger})"
        panel = Panel(content, title=title, expand=False)
        console.print(panel)


__all__ = [
    "console",
    "render_file_content_preview",
    "render_hints",
    "render_plan_files",
    "render_root_edits",
    "render_spec_panel",
    "render_validation_errors",
]

"""Interactive prompts for tailor CLI wizard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.prompt import Confirm, Prompt
from rich.table import Table

from tailor.core.config import MAX_CONTEXT_FILES, MAX_JOB_FILES
from tailor.display.console import (
    ICON_DOC,
    ICON_FILE,
    ICON_SUCCESS,
    ICON_TEMPLATE,
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_HIGHLIGHT,
    STYLE_SUCCESS,
    console,
    format_size,
)

if TYPE_CHECKING:
    from tailor.models.templates import TemplateInfo


def prompt_files(
    prompt_text: str,
    *,
    max_files: int,
) -> list[Path]:
    """Prompt user to enter file paths one by one.

    Args:
        prompt_text: Description to show before file input.
        max_files: Maximum number of files allowed.

    Returns:
        List of validated file paths.
    """
    console.print(f"\n{prompt_text}")
    console.print(f"[{STYLE_DIM}]Press Enter after each file, empty line when done.[/]")
    console.print(f"[{STYLE_DIM}]Maximum {max_files} files.[/]\n")

    files: list[Path] = []
    file_num = 1

    while len(files) < max_files:
        try:
            path_str = Prompt.ask(f"  File {file_num}")
        except KeyboardInterrupt:
            console.print("\n[dim]Cancelled[/dim]")
            break

        if not path_str.strip():
            if files:
                break
            console.print(f"  [{STYLE_ERROR}]At least one file is required[/]")
            continue

        path = Path(path_str.strip()).expanduser()

        if not path.exists():
            console.print(f"  [{STYLE_ERROR}]File not found: {path}[/]")
            continue

        if not path.is_file():
            console.print(f"  [{STYLE_ERROR}]Not a file: {path}[/]")
            continue

        size = path.stat().st_size
        files.append(path)
        console.print(f"  {ICON_SUCCESS} {path.name} ({format_size(size)})", style=STYLE_SUCCESS)
        file_num += 1

    return files


def prompt_context_files() -> list[Path]:
    """Prompt for personal context files."""
    return prompt_files(
        f"{ICON_FILE} Personal Context Files",
        max_files=MAX_CONTEXT_FILES,
    )


def prompt_job_files() -> list[Path]:
    """Prompt for job listing files."""
    return prompt_files(
        f"{ICON_DOC} Job Listing Files",
        max_files=MAX_JOB_FILES,
    )


def prompt_template_selection(templates: list[TemplateInfo]) -> TemplateInfo | None:
    """Display template selection menu.

    Args:
        templates: List of available templates.

    Returns:
        Selected template or None if cancelled.
    """
    console.print(f"\n{ICON_TEMPLATE} Select Template")
    console.print()

    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column("#", justify="center", width=4)
    table.add_column("Name", style="cyan bold")
    table.add_column("Description")
    table.add_column("Version", justify="center", width=10)

    for i, template in enumerate(templates, 1):
        table.add_row(
            f"[{i}]",
            template.name,
            template.description[:50] + "..." if len(template.description) > 50 else template.description,
            template.version,
        )

    console.print(table)
    console.print()

    while True:
        try:
            choice = Prompt.ask(
                f"Select template [1-{len(templates)}]",
                default="1",
            )
        except KeyboardInterrupt:
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(templates):
                selected = templates[idx]
                console.print(f"\n  {ICON_SUCCESS} Using template: ", style=STYLE_SUCCESS, end="")
                console.print(f"{selected.name}", style=STYLE_HIGHLIGHT, end="")
                console.print(f" (v{selected.version})", style=STYLE_DIM)
                return selected
        except ValueError:
            pass

        console.print(f"  [{STYLE_ERROR}]Invalid selection[/]")


def prompt_output_path(default_path: str) -> Path:
    """Prompt for output file path."""
    path_str = Prompt.ask("  Output path", default=default_path)
    return Path(path_str).expanduser()


def prompt_confirm_generation() -> bool:
    """Prompt to confirm document generation."""
    console.print()
    return Confirm.ask("Generate document?", default=True)


def display_step_header(step: int, total: int, title: str) -> None:
    """Display a step header in the wizard."""
    console.print()
    console.rule(f"[bold]Step {step}/{total}: {title}[/bold]", style="cyan")

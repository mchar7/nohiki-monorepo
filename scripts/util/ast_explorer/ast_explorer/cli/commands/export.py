"""Export command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.cli.commands.scan import parse_format
from ast_explorer.cli.display import console
from ast_explorer.cli.utils import extract_codebase, validate_path
from ast_explorer.models.codebase import export_codebase


def export_cmd(
    path: Annotated[Path, typer.Argument(help="Path to scan")] = Path(),
    output: Annotated[Path, typer.Option("--output", "-o", help="Output file")] = Path("codebase.md"),
    fmt: Annotated[str, typer.Option("--format", "-f", help="Output format: json, yaml, markdown")] = "markdown",
) -> None:
    """Export codebase AST to a file."""
    root = validate_path(path)
    codebase = extract_codebase(root)

    export_fmt = parse_format(fmt)
    content = export_codebase(codebase, export_fmt)

    output.write_text(content)
    console.print(f"[green]✓[/green] Exported {codebase.file_count} files to [cyan]{output}[/cyan]")
    console.print(f"[dim]Format: {export_fmt.value}, Symbols: {codebase.total_symbols}[/dim]")

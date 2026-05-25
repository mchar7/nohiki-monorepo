"""Scan command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.cli.display import (
    console,
    print_directory_table,
    print_file_tree,
    print_summary_panel,
)
from ast_explorer.cli.utils import extract_codebase, validate_path
from ast_explorer.models.codebase import CodebaseAST, ExportFormat, export_codebase


def scan_cmd(
    path: Annotated[Path, typer.Argument(help="Path to scan")] = Path(),
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file")] = None,
    fmt: Annotated[str, typer.Option("--format", "-f", help="Output format: json, yaml, markdown")] = "json",
    tree: Annotated[bool, typer.Option("--tree", "-t", help="Show file tree")] = False,
    symbols: Annotated[bool, typer.Option("--symbols", "-s", help="Show symbols in tree")] = False,
) -> None:
    """Scan a directory and extract AST information."""
    root = validate_path(path)
    codebase = extract_codebase(root)

    print_summary_panel(codebase)

    if tree:
        console.print()
        print_file_tree(codebase, show_symbols=symbols)

    if output:
        _export_to_file(codebase, output, fmt)
    else:
        console.print()
        print_directory_table(codebase)


def _export_to_file(codebase: CodebaseAST, output: Path, fmt: str) -> None:
    """Export codebase to file."""
    export_fmt = parse_format(fmt)
    content = export_codebase(codebase, export_fmt)
    output.write_text(content)
    console.print(f"\n[green]✓[/green] Exported to [cyan]{output}[/cyan]")


def parse_format(fmt: str) -> ExportFormat:
    """Parse format string to ExportFormat enum."""
    fmt_map: dict[str, ExportFormat] = {
        "json": ExportFormat.JSON,
        "yaml": ExportFormat.YAML,
        "yml": ExportFormat.YAML,
        "markdown": ExportFormat.MARKDOWN,
        "md": ExportFormat.MARKDOWN,
    }
    if fmt.lower() not in fmt_map:
        valid = ", ".join(fmt_map.keys())
        console.print(f"[red]Invalid format: {fmt}[/red]")
        console.print(f"[dim]Valid formats: {valid}[/dim]")
        raise typer.Exit(1)
    return fmt_map[fmt.lower()]

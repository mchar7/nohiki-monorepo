"""Inspect command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.cli.display import console, print_symbol_detail
from ast_explorer.cli.utils import extract_codebase, validate_path
from ast_explorer.models.codebase import CodebaseAST


def inspect_cmd(
    symbol_name: Annotated[str, typer.Argument(help="Symbol name to inspect")],
    path: Annotated[Path, typer.Option("--path", "-p", help="Path to scan")] = Path(),
) -> None:
    """Inspect a specific symbol by name."""
    root = validate_path(path)
    codebase = extract_codebase(root)

    if symbol := codebase.find_symbol(symbol_name):
        print_symbol_detail(symbol)
        return

    _print_symbol_suggestions(symbol_name, codebase)
    raise typer.Exit(1)


def _print_symbol_suggestions(symbol_name: str, codebase: CodebaseAST) -> None:
    """Print suggestions for similar symbol names."""
    matches = codebase.search_symbols(symbol_name)
    if matches:
        console.print(f"[yellow]Symbol '{symbol_name}' not found. Did you mean:[/yellow]")
        for match in matches[:10]:
            console.print(f"  • {match.qualified_name}")
    else:
        console.print(f"[red]Symbol not found: {symbol_name}[/red]")

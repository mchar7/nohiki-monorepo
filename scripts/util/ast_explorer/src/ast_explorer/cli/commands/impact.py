"""Impact analysis command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.cli.display import console
from ast_explorer.cli.utils import extract_codebase, validate_path
from ast_explorer.models.codebase import CodebaseAST


def impact_cmd(
    symbol_name: Annotated[str, typer.Argument(help="Symbol name to analyze")],
    path: Annotated[Path, typer.Option("--path", "-p", help="Path to scan")] = Path(),
) -> None:
    """Analyze impact of changing a symbol across packages."""
    from ast_explorer.analysis.dependency_analyzer import analyze_dependencies, get_symbol_impact
    from ast_explorer.cli.display_deps import print_impact_analysis

    root = validate_path(path)
    codebase = extract_codebase(root)
    dep_graph = analyze_dependencies(codebase)
    analysis = get_symbol_impact(symbol_name, codebase, dep_graph)

    if not analysis:
        _handle_impact_not_found(symbol_name, codebase)
        raise typer.Exit(1)

    print_impact_analysis(analysis)


def _handle_impact_not_found(symbol_name: str, codebase: CodebaseAST) -> None:
    """Handle case when symbol is not found for impact analysis."""
    console.print(f"[yellow]Symbol not found: {symbol_name}[/yellow]")
    matches = codebase.search_symbols(symbol_name)
    if matches:
        console.print("[dim]Did you mean:[/dim]")
        for m in matches[:10]:
            console.print(f"  • {m.qualified_name}")

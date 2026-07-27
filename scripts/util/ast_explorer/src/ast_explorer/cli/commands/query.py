"""Query command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.analysis.query import QueryFilter, get_public_api, query_symbols
from ast_explorer.cli.display import console, print_symbols_table
from ast_explorer.cli.utils import extract_codebase, validate_path
from ast_explorer.models.nodes import NodeKind


def query_cmd(
    path: Annotated[Path, typer.Argument(help="Path to scan")] = Path(),
    kind: Annotated[str | None, typer.Option("--kind", "-k", help="Filter by kind: class, function, method")] = None,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Filter by name pattern")] = None,
    file: Annotated[str | None, typer.Option("--file", help="Filter by file path")] = None,
    decorator: Annotated[str | None, typer.Option("--decorator", "-d", help="Filter by decorator")] = None,
    public_only: Annotated[bool, typer.Option("--public", "-p", help="Show only public API")] = False,
    include_tests: Annotated[bool, typer.Option("--include-tests", help="Include test files in results")] = False,
) -> None:
    """Query symbols from the codebase."""
    root = validate_path(path)
    codebase = extract_codebase(root)

    if public_only:
        symbols = get_public_api(codebase, include_tests=include_tests)
    else:
        query_filter = _build_filter(kind=kind, name=name, file=file, decorator=decorator)
        symbols = query_symbols(codebase, query_filter, include_tests=include_tests)

    if not symbols:
        console.print("[yellow]No symbols found matching criteria[/yellow]")
        raise typer.Exit(0)

    test_note = "" if include_tests else " [dim](test files excluded)[/dim]"
    print_symbols_table(symbols, title=f"Found {len(symbols)} symbols{test_note}")


def _build_filter(
    kind: str | None = None,
    name: str | None = None,
    file: str | None = None,
    decorator: str | None = None,
) -> QueryFilter:
    """Build a QueryFilter from CLI options."""
    kinds: frozenset[NodeKind] | None = None
    if kind:
        kind_map: dict[str, frozenset[NodeKind]] = {
            "class": frozenset({NodeKind.CLASS}),
            "function": frozenset({NodeKind.FUNCTION, NodeKind.ASYNC_FUNCTION}),
            "method": frozenset({NodeKind.METHOD, NodeKind.ASYNC_METHOD}),
            "property": frozenset({NodeKind.PROPERTY}),
            "variable": frozenset({NodeKind.VARIABLE, NodeKind.CONSTANT}),
            "type": frozenset({NodeKind.TYPE_ALIAS, NodeKind.PROTOCOL}),
        }
        kinds = kind_map.get(kind.lower())
        if kinds is None:
            valid = ", ".join(kind_map.keys())
            console.print(f"[red]Invalid kind: {kind}[/red]")
            console.print(f"[dim]Valid kinds: {valid}[/dim]")
            raise typer.Exit(1)

    return QueryFilter(
        kinds=kinds,
        name_pattern=name,
        in_file=file,
        has_decorator=decorator,
    )

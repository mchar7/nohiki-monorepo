"""Dependency analysis command for AST Explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ast_explorer.cli.display import console
from ast_explorer.cli.utils import extract_codebase, validate_path


def deps_cmd(
    path: Annotated[Path, typer.Argument(help="Path to scan")] = Path(),
    package: Annotated[str | None, typer.Option("--package", "-p", help="Show deps for specific package")] = None,
    lib: Annotated[str | None, typer.Option("--lib", "-l", help="Show usages of a shared library")] = None,
) -> None:
    """Analyze cross-package dependencies."""
    from ast_explorer.analysis.dependency_analyzer import analyze_dependencies
    from ast_explorer.cli.display_deps import (
        print_cross_service_dependencies,
        print_package_dependencies,
        print_shared_lib_usage,
    )

    root = validate_path(path)
    codebase = extract_codebase(root)
    dep_graph = analyze_dependencies(codebase)

    if lib:
        if usages := dep_graph.get_shared_lib_usage(lib):
            print_shared_lib_usage(lib, usages)
        else:
            console.print(f"[yellow]No usages found for library: {lib}[/yellow]")
            raise typer.Exit(0)
        return

    if package:
        if deps := dep_graph.get_package_dependencies(package):
            print_package_dependencies(package, deps, dep_graph)
        else:
            console.print(f"[yellow]No dependencies found for package: {package}[/yellow]")
            raise typer.Exit(0)
        return

    cross_deps = dep_graph.get_cross_service_dependencies()
    print_cross_service_dependencies(cross_deps)

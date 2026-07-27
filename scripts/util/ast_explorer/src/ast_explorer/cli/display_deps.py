"""Display functions for dependency analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from ast_explorer.models.dependencies import DependencyGraph, ImpactAnalysis, PackageDependency


console = Console()


def print_shared_lib_usage(lib: str, usages: list[PackageDependency]) -> None:
    """Print usage of a shared library across packages."""
    console.print(Panel(f"[bold]{lib}[/bold] usages", title="Shared Library"))

    table = Table(show_header=True)
    table.add_column("Package", style="cyan")
    table.add_column("Type")
    table.add_column("Imports")
    table.add_column("Symbols")

    for dep in usages:
        symbols_preview = _format_symbols_preview(dep.imported_symbols)
        table.add_row(
            dep.source_package.name,
            dep.source_package.package_type.value,
            str(dep.import_count),
            symbols_preview,
        )

    console.print(table)


def _format_symbols_preview(symbols: set[str], max_display: int = 5) -> str:
    """Format symbols for display with truncation."""
    symbols_list = sorted(symbols)[:max_display]
    preview = ", ".join(symbols_list)
    if len(symbols) > max_display:
        preview += "..."
    return preview


def print_package_dependencies(package: str, deps: list[PackageDependency], dep_graph: DependencyGraph) -> None:
    """Print dependencies for a specific package."""
    pkg = dep_graph.packages.get(package)
    pkg_type = pkg.package_type.value if pkg else "unknown"

    console.print(Panel(f"[bold]{package}[/bold] ({pkg_type})", title="Package Dependencies"))

    table = Table(show_header=True)
    table.add_column("Dependency", style="cyan")
    table.add_column("Imports")
    table.add_column("Symbols")

    for dep in deps:
        symbols_preview = _format_symbols_preview(dep.imported_symbols)
        table.add_row(dep.target_package, str(dep.import_count), symbols_preview)

    console.print(table)

    dependents = dep_graph.get_dependents(package)
    if dependents:
        console.print(f"\n[bold]Depended on by:[/bold] {', '.join(dependents)}")


def print_cross_service_dependencies(cross_deps: dict[str, list[str]]) -> None:
    """Print shared library usage by services."""
    table = Table(title="Shared Library Usage by Services", show_header=True)
    table.add_column("Library", style="cyan")
    table.add_column("Used By Services")

    for lib_name, services in sorted(cross_deps.items()):
        table.add_row(lib_name, ", ".join(sorted(services)))

    console.print(table)


def print_impact_analysis(analysis: ImpactAnalysis) -> None:
    """Print impact analysis for a symbol."""
    _print_impact_header(analysis)
    _print_impact_warnings(analysis)
    _print_affected_packages(analysis)
    _print_affected_services(analysis)
    _print_direct_imports(analysis)


def _print_impact_header(analysis: ImpactAnalysis) -> None:
    """Print impact analysis header panel."""
    console.print(
        Panel(
            f"[bold]{analysis.symbol_qualified_name}[/bold]\n"
            f"Defined in: {analysis.defined_in_package} ({analysis.defined_in_file.name})",
            title="Impact Analysis",
        )
    )


def _print_impact_warnings(analysis: ImpactAnalysis) -> None:
    """Print cross-package/service warnings."""
    if analysis.is_cross_package:
        console.print("[bold yellow]⚠ Cross-package symbol[/bold yellow]")
    if analysis.is_cross_service:
        console.print("[bold red]⚠ Cross-service symbol - changes may require coordination[/bold red]")


def _print_affected_packages(analysis: ImpactAnalysis) -> None:
    """Print list of affected packages."""
    if not analysis.affected_packages:
        return

    console.print(f"\n[bold]Affected packages ({len(analysis.affected_packages)}):[/bold]")
    for pkg in sorted(analysis.affected_packages):
        console.print(f"  • {pkg}")


def _print_affected_services(analysis: ImpactAnalysis) -> None:
    """Print list of affected services."""
    if not analysis.affected_services:
        return

    console.print(f"\n[bold]Affected services ({len(analysis.affected_services)}):[/bold]")
    for svc in sorted(analysis.affected_services):
        console.print(f"  • {svc}")


def _print_direct_imports(analysis: ImpactAnalysis, max_display: int = 20) -> None:
    """Print table of direct imports."""
    if not analysis.direct_imports:
        return

    table = Table(title=f"Direct Imports ({len(analysis.direct_imports)})", show_header=True)
    table.add_column("File", style="cyan")
    table.add_column("Line")
    table.add_column("Import")

    for imp in analysis.direct_imports[:max_display]:
        import_str = f"from {imp.module} import {', '.join(imp.names)}"
        table.add_row(str(imp.file_path.name), str(imp.line), import_str)

    console.print(table)

    remaining = len(analysis.direct_imports) - max_display
    if remaining > 0:
        console.print(f"[dim]... and {remaining} more[/dim]")

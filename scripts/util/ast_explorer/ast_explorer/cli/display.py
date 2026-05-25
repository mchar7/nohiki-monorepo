"""Rich display helpers for CLI output."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from ast_explorer.models.nodes import NodeKind

if TYPE_CHECKING:
    from pathlib import Path

    from ast_explorer.models.codebase import CodebaseAST
    from ast_explorer.models.nodes import SymbolNode

console = Console(stderr=True)


def create_progress() -> Progress:
    """Create a progress bar for file scanning."""
    return Progress(
        SpinnerColumn(),
        TaskProgressColumn(),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.completed}/{task.total}"),
        TextColumn("({task.description})", justify="right"),
        console=console,
        expand=False,
    )


def print_summary_panel(codebase: CodebaseAST) -> None:
    """Print a summary panel of the codebase analysis."""
    summary = codebase.get_summary()

    content = f"[bold]Files:[/bold] {summary['files']}\n[bold]Total Symbols:[/bold] {summary['total_symbols']}\n"

    if class_count := summary.get("class"):
        content += f"[bold]Classes:[/bold] {class_count}\n"

    if funcs := summary.get("function", 0) + summary.get("async_function", 0):
        content += f"[bold]Functions:[/bold] {funcs}\n"

    if methods := summary.get("method", 0) + summary.get("async_method", 0):
        content += f"[bold]Methods:[/bold] {methods}\n"

    if errors := summary.get("files_with_errors"):
        content += f"[yellow]Files with errors:[/yellow] {errors}\n"

    if test_files := summary.get("test_files"):
        content += f"[dim]Test files (excluded):[/dim] {test_files}\n"

    panel = Panel(
        content.strip(),
        title=f"[bold cyan]AST Summary: {codebase.root.name}[/bold cyan]",
        border_style="cyan",
    )
    console.print(panel)


def print_directory_table(codebase: CodebaseAST) -> None:
    """Print a table of directory statistics."""
    stats = codebase.get_directory_stats()
    if not stats:
        return

    table = Table(
        title="[bold]Directory Structure[/bold]",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Directory", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Symbols", justify="right")
    table.add_column("Classes", justify="right")
    table.add_column("Functions", justify="right")

    for dir_path in sorted(stats.keys()):
        dir_stats = stats[dir_path]
        table.add_row(
            str(dir_path) or ".",
            str(dir_stats.file_count),
            str(dir_stats.symbol_count),
            str(dir_stats.class_count),
            str(dir_stats.function_count),
        )

    console.print(table)


def print_file_tree(codebase: CodebaseAST, *, show_symbols: bool = False) -> None:
    """Print a tree view of files and optionally symbols."""
    tree = Tree(f"[bold cyan]{codebase.root.name}[/bold cyan]")

    dir_nodes: dict[Path, Tree] = {}

    sorted_files = sorted(codebase.files.values(), key=lambda f: str(f.relative_path))

    for file_ast in sorted_files:
        parent = file_ast.relative_path.parent
        if parent not in dir_nodes:
            dir_nodes[parent] = _create_dir_branch(tree, parent)

        file_node = dir_nodes[parent].add(
            f"[green]{file_ast.relative_path.name}[/green] [dim]({file_ast.symbol_count} symbols)[/dim]"
        )

        if show_symbols:
            for symbol in file_ast.symbols:
                _add_symbol_to_tree(file_node, symbol)

    console.print(tree)


def _create_dir_branch(tree: Tree, path: Path) -> Tree:
    """Create a directory branch in the tree."""
    parts = path.parts
    current = tree
    for part in parts:
        found = False
        for child in current.children:
            if str(part) in str(child.label):
                current = child
                found = True
                break
        if not found:
            current = current.add(f"[blue]{part}/[/blue]")
    return current


def _add_symbol_to_tree(parent: Tree, symbol: SymbolNode) -> None:
    """Add a symbol and its children to a tree node."""
    icon = _get_kind_icon(symbol.kind)
    label = f"{icon} [yellow]{symbol.name}[/yellow]"
    if symbol.kind in {NodeKind.CLASS, NodeKind.PROTOCOL}:
        label = f"{icon} [magenta]{symbol.name}[/magenta]"

    node = parent.add(label)
    for child in symbol.children:
        _add_symbol_to_tree(node, child)


def _get_kind_icon(kind: NodeKind) -> str:
    """Get an icon for a symbol kind."""
    icons: dict[NodeKind, str] = {
        NodeKind.CLASS: "📦",
        NodeKind.PROTOCOL: "📋",
        NodeKind.INTERFACE: "📋",
        NodeKind.FUNCTION: "⚡",
        NodeKind.ASYNC_FUNCTION: "⚡",
        NodeKind.METHOD: "🔧",
        NodeKind.ASYNC_METHOD: "🔧",
        NodeKind.PROPERTY: "🏷️",
        NodeKind.VARIABLE: "📝",
        NodeKind.CONSTANT: "🔒",
        NodeKind.TYPE_ALIAS: "🔤",
        NodeKind.ENUM: "📊",
    }
    return icons.get(kind, "•")


def print_symbols_table(symbols: list[SymbolNode], *, title: str = "Symbols") -> None:
    """Print a table of symbols."""
    table = Table(title=f"[bold]{title}[/bold]", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Kind")
    table.add_column("File", style="dim")
    table.add_column("Line", justify="right")
    table.add_column("Signature")

    for symbol in symbols[:100]:
        kind_icon = _get_kind_icon(symbol.kind)
        table.add_row(
            symbol.qualified_name,
            f"{kind_icon} {symbol.kind.value}",
            str(symbol.file_path.name),
            str(symbol.span.start.line + 1),
            symbol.to_signature_string()[:60],
        )

    console.print(table)

    if len(symbols) > 100:
        console.print(f"[dim]...and {len(symbols) - 100} more symbols[/dim]")


def print_symbol_detail(symbol: SymbolNode) -> None:
    """Print detailed information about a symbol."""
    content = f"[bold]Name:[/bold] {symbol.qualified_name}\n"
    content += f"[bold]Kind:[/bold] {symbol.kind.value}\n"
    content += f"[bold]File:[/bold] {symbol.file_path}\n"
    content += f"[bold]Lines:[/bold] {symbol.span.start.line + 1}-{symbol.span.end.line + 1}\n"
    content += f"[bold]Visibility:[/bold] {symbol.visibility.value}\n"

    if symbol.signature:
        content += f"[bold]Signature:[/bold] {symbol.to_signature_string()}\n"

    if symbol.decorators:
        content += f"[bold]Decorators:[/bold] {', '.join(symbol.decorators)}\n"

    if symbol.bases:
        content += f"[bold]Bases:[/bold] {', '.join(symbol.bases)}\n"

    if symbol.docstring:
        doc_preview = symbol.docstring[:200]
        if len(symbol.docstring) > 200:
            doc_preview += "..."
        content += f"\n[bold]Docstring:[/bold]\n{doc_preview}\n"

    panel = Panel(
        content.strip(),
        title=f"[bold cyan]{symbol.name}[/bold cyan]",
        border_style="cyan",
    )
    console.print(panel)

    if symbol.children:
        console.print("\n[bold]Children:[/bold]")
        for child in symbol.children:
            icon = _get_kind_icon(child.kind)
            console.print(f"  {icon} {child.name}")

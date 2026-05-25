"""CLI utility functions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from ast_explorer.analysis.extractor import ASTExtractor
from ast_explorer.cli.display import console, create_progress

if TYPE_CHECKING:
    from ast_explorer.models.codebase import CodebaseAST

SCANNING_MESSAGE = "[cyan]Scanning..."


def validate_path(path: Path) -> Path:
    """Validate path exists and return resolved path."""
    root = path.resolve()
    if not root.exists():
        console.print(f"[red]Path does not exist: {root}[/red]")
        raise typer.Exit(1)
    return root


def extract_codebase(root: Path) -> CodebaseAST:
    """Extract codebase AST with progress display."""
    extractor = ASTExtractor(root)

    with create_progress() as progress:
        task = progress.add_task(SCANNING_MESSAGE, total=None)

        def on_progress(file_path: Path, current: int, total: int) -> None:
            progress.update(task, completed=current, total=total, description=f"[cyan]{file_path.name}")

        codebase = extractor.extract(progress_callback=on_progress)

    console.print()
    return codebase

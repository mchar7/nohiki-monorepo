"""AST extraction engine."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ast_explorer.analysis.scanner import FileScanner
from ast_explorer.models.codebase import CodebaseAST, FileAST
from ast_explorer.parsers.registry import LanguageRegistry, get_default_registry

if TYPE_CHECKING:
    from collections.abc import Callable


class ASTExtractor:
    """Extracts AST information from a codebase.

    Coordinates file scanning, parsing, and AST assembly into a queryable
    CodebaseAST structure.
    """

    def __init__(
        self,
        root: Path,
        registry: LanguageRegistry | None = None,
        excludes: frozenset[str] | None = None,
    ) -> None:
        """Initialize extractor with root path and optional configuration."""
        self.root = root.resolve()
        self.registry = registry or get_default_registry()
        self.excludes = excludes

    def extract(
        self,
        progress_callback: Callable[[Path, int, int], None] | None = None,
    ) -> CodebaseAST:
        """Extract AST from all supported files in the codebase.

        Args:
            progress_callback: Optional callback(path, current, total) for progress.

        Returns:
            CodebaseAST containing all parsed files.
        """
        scanner = FileScanner(
            root=self.root,
            extensions=self.registry.supported_extensions,
            excludes=self.excludes,
        )

        files = list(scanner.scan())
        total = len(files)

        codebase = CodebaseAST(
            root=self.root,
            excluded_patterns=self.excludes or frozenset(),
        )

        for idx, file_path in enumerate(files, 1):
            if progress_callback:
                progress_callback(file_path, idx, total)

            if file_ast := self._parse_file(file_path):
                codebase.add_file(file_ast)

        return codebase

    def extract_file(self, path: Path) -> FileAST | None:
        """Extract AST from a single file."""
        return self._parse_file(path.resolve())

    def _parse_file(self, path: Path) -> FileAST | None:
        """Parse a single file and return its FileAST."""
        parser = self.registry.get_parser_for_file(path)
        if not parser:
            return None

        try:
            source = path.read_bytes()
        except OSError:
            return FileAST(
                path=path,
                relative_path=path.relative_to(self.root),
                language=parser.language_name,
                parse_errors=[f"Could not read file: {path}"],
            )

        symbols, errors = parser.parse_file(path, source)

        return FileAST(
            path=path,
            relative_path=path.relative_to(self.root),
            language=parser.language_name,
            symbols=symbols,
            parse_errors=errors,
        )

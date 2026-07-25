"""Codebase-level domain models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum, auto
from io import StringIO
from pathlib import Path

import yaml

from ast_explorer.models.nodes import NodeKind, SymbolNode


class ExportFormat(StrEnum):
    """Supported export formats."""

    JSON = auto()
    YAML = auto()
    MARKDOWN = auto()


@dataclass(slots=True)
class FileAST:
    """AST representation of a single source file."""

    path: Path
    relative_path: Path
    language: str
    symbols: list[SymbolNode] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Check if file had parse errors."""
        return len(self.parse_errors) > 0

    @property
    def symbol_count(self) -> int:
        """Count all symbols including nested ones."""
        return sum(len(s.walk()) for s in self.symbols)

    def get_classes(self) -> list[SymbolNode]:
        """Get all class definitions in this file."""
        return [s for s in self._all_symbols() if s.kind == NodeKind.CLASS]

    def get_functions(self) -> list[SymbolNode]:
        """Get all top-level function definitions."""
        return [s for s in self._all_symbols() if s.kind in {NodeKind.FUNCTION, NodeKind.ASYNC_FUNCTION}]

    def _all_symbols(self) -> list[SymbolNode]:
        """Flatten all symbols including nested ones."""
        result: list[SymbolNode] = []
        for symbol in self.symbols:
            result.extend(symbol.walk())
        return result

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "path": str(self.relative_path),
            "language": self.language,
            "symbol_count": self.symbol_count,
            "has_errors": self.has_errors,
            "symbols": [s.to_dict() for s in self.symbols],
        }


@dataclass(slots=True)
class DirectoryStats:
    """Statistics for a directory in the codebase."""

    path: Path
    file_count: int = 0
    symbol_count: int = 0
    class_count: int = 0
    function_count: int = 0
    error_count: int = 0


@dataclass(slots=True)
class CodebaseAST:
    """Complete AST representation of a codebase.

    This is the top-level container that holds all parsed file ASTs
    and provides query capabilities across the entire codebase.
    """

    root: Path
    files: dict[Path, FileAST] = field(default_factory=dict)
    excluded_patterns: frozenset[str] = field(default_factory=frozenset)
    _symbol_index: dict[str, SymbolNode] = field(default_factory=dict, repr=False, compare=False)

    @property
    def file_count(self) -> int:
        """Count of parsed files."""
        return len(self.files)

    @property
    def test_file_count(self) -> int:
        """Count of test files."""
        return sum(1 for f in self.files.values() if "test" in f.path.name.lower() or "tests" in f.path.parts)

    @property
    def total_symbols(self) -> int:
        """Total count of all symbols across all code files (excluding tests by default)."""
        return sum(f.symbol_count for f in self.files.values() if not self._is_test_file(f))

    def _is_test_file(self, file_ast: FileAST) -> bool:
        """Check if a file is a test file."""
        return "test" in file_ast.path.name.lower() or "tests" in file_ast.path.parts

    def get_summary(self) -> dict[str, int]:
        """Get a summary of the codebase statistics."""
        code_files = [f for f in self.files.values() if not self._is_test_file(f)]
        all_symbols = [s for f in code_files for symbol in f.symbols for s in symbol.walk()]

        kind_counts: dict[str, int] = {}
        for symbol in all_symbols:
            kind_counts[symbol.kind.value] = kind_counts.get(symbol.kind.value, 0) + 1

        return {
            "files": len(code_files),
            "test_files": self.test_file_count,
            "total_symbols": len(all_symbols),
            "files_with_errors": len(self.files_with_errors),
            **kind_counts,
        }

    @property
    def files_with_errors(self) -> list[FileAST]:
        """List of files that had parse errors."""
        return [f for f in self.files.values() if f.has_errors]

    def add_file(self, file_ast: FileAST) -> None:
        """Add a parsed file to the codebase and update symbol index."""
        self.files[file_ast.path] = file_ast
        for symbol in file_ast.symbols:
            for s in symbol.walk():
                self._symbol_index[s.qualified_name] = s

    def get_file(self, path: Path) -> FileAST | None:
        """Get a file by its path."""
        return self.files.get(path)

    def get_all_symbols(self, *, include_tests: bool = False) -> list[SymbolNode]:
        """Get all symbols across all files."""
        result: list[SymbolNode] = []
        for file_ast in self.files.values():
            if not include_tests and self._is_test_file(file_ast):
                continue
            for symbol in file_ast.symbols:
                result.extend(symbol.walk())
        return result

    def get_symbols_by_kind(self, kind: NodeKind, *, include_tests: bool = False) -> list[SymbolNode]:
        """Get all symbols of a specific kind across all files."""
        return [s for s in self.get_all_symbols(include_tests=include_tests) if s.kind == kind]

    def get_classes(self, *, include_tests: bool = False) -> list[SymbolNode]:
        """Get all class definitions."""
        return self.get_symbols_by_kind(NodeKind.CLASS, include_tests=include_tests)

    def get_functions(self, *, include_tests: bool = False) -> list[SymbolNode]:
        """Get all function definitions."""
        funcs = self.get_symbols_by_kind(NodeKind.FUNCTION, include_tests=include_tests)
        async_funcs = self.get_symbols_by_kind(NodeKind.ASYNC_FUNCTION, include_tests=include_tests)
        return funcs + async_funcs

    def find_symbol(self, qualified_name: str) -> SymbolNode | None:
        """Find a symbol by its qualified name using O(1) index lookup."""
        return self._symbol_index.get(qualified_name)

    def search_symbols(self, pattern: str, *, include_tests: bool = False) -> list[SymbolNode]:
        """Search symbols by name pattern (case-insensitive contains)."""
        pattern_lower = pattern.lower()
        symbols = self._symbol_index.values()
        if not include_tests:
            symbols = [s for s in symbols if not self._is_test_path(s.file_path)]
        return [s for s in symbols if pattern_lower in s.name.lower()]

    def _is_test_path(self, path: Path) -> bool:
        """Check if a path belongs to a test."""
        return "test" in path.name.lower() or "tests" in path.parts

    def get_directory_stats(self) -> dict[Path, DirectoryStats]:
        """Compute statistics grouped by directory."""
        stats_by_dir: dict[Path, DirectoryStats] = {}

        for file_ast in self.files.values():
            dir_path = file_ast.relative_path.parent
            stats = stats_by_dir.setdefault(dir_path, DirectoryStats(path=dir_path))

            stats.file_count += 1
            stats.symbol_count += file_ast.symbol_count
            stats.class_count += len(file_ast.get_classes())
            stats.function_count += len(file_ast.get_functions())
            stats.error_count += len(file_ast.parse_errors)

        return stats_by_dir

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        sorted_files = sorted(self.files.values(), key=lambda f: str(f.relative_path))
        return {
            "root": str(self.root),
            "summary": self.get_summary(),
            "files": [f.to_dict() for f in sorted_files],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False, allow_unicode=True)

    def to_markdown(self) -> str:
        """Serialize to Markdown for LLM context."""
        out = StringIO()
        out.write(f"# Codebase AST: {self.root.name}\n\n")
        self._write_md_summary(out)
        self._write_md_dirs(out)
        self._write_md_files(out)
        return out.getvalue()

    def _write_md_summary(self, out: StringIO) -> None:
        summary = self.get_summary()
        out.write("## Summary\n\n")
        out.write(f"- **Files**: {summary['files']}\n")
        out.write(f"- **Total Symbols**: {summary['total_symbols']}\n")
        if "class" in summary:
            out.write(f"- **Classes**: {summary['class']}\n")
        funcs = summary.get("function", 0) + summary.get("async_function", 0)
        if funcs:
            out.write(f"- **Functions**: {funcs}\n")
        out.write("\n")

    def _write_md_dirs(self, out: StringIO) -> None:
        stats = self.get_directory_stats()
        if not stats:
            return
        out.write("## Directory Structure\n\n")
        out.write("| Directory | Files | Symbols | Classes | Functions |\n")
        out.write("|-----------|-------|---------|---------|----------|\n")
        for dir_path in sorted(stats.keys()):
            s = stats[dir_path]
            d = dir_path or "."
            out.write(f"| `{d}` | {s.file_count} | {s.symbol_count} | {s.class_count} | {s.function_count} |\n")
        out.write("\n")

    def _write_md_files(self, out: StringIO) -> None:
        out.write("## Files\n\n")
        for file_ast in sorted(self.files.values(), key=lambda f: str(f.relative_path)):
            out.write(f"### `{file_ast.relative_path}`\n\n")
            if file_ast.has_errors:
                out.write("⚠️ **Parse errors detected**\n\n")
            if not file_ast.symbols:
                out.write("*No symbols extracted*\n\n")
                continue
            for symbol in file_ast.symbols:
                self._write_md_symbol(out, symbol, 0)
            out.write("\n")

    def _write_md_symbol(self, out: StringIO, symbol: SymbolNode, depth: int) -> None:
        indent = "  " * depth
        icon = _MD_ICONS.get(symbol.kind, "•")
        out.write(f"{indent}- {icon} `{symbol.to_signature_string()}`")
        if symbol.docstring:
            doc = symbol.docstring[:80].replace("\n", " ")
            out.write(f" -- *{doc}{'...' if len(symbol.docstring) > 80 else ''}*")
        out.write(f" (L{symbol.span.start.line + 1})\n")
        for child in symbol.children:
            self._write_md_symbol(out, child, depth + 1)


_MD_ICONS: dict[NodeKind, str] = {
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
    NodeKind.ENUM_MEMBER: "•",
}


def export_codebase(codebase: CodebaseAST, fmt: ExportFormat) -> str:
    """Export codebase to string in the specified format."""
    match fmt:
        case ExportFormat.JSON:
            return codebase.to_json()
        case ExportFormat.YAML:
            return codebase.to_yaml()
        case ExportFormat.MARKDOWN:
            return codebase.to_markdown()
        case _:
            msg = f"Unknown format: {fmt}"
            raise ValueError(msg)

#!/usr/bin/env python3
"""Repository scale analyzer.

Summarizes tracked, non-ignored project files with an emphasis on real code:
- Excludes gitignored paths, lockfiles, caches, temp files, and specific docs notes.
- Counts code files and lines of code (non-empty, non-comment) across languages.
- Breaks down by repository section (backend/libs/typescript/tests/etc.) and file kind.
- Optional AST-based symbol counting via ast_explorer integration.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console(stderr=True)

# Configuration

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

LOCKFILE_NAMES: Final[set[str]] = {
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
    "flake.lock",
}

SKIP_DIR_FRAGMENTS: Final[set[str]] = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "coverage",
}

SKIP_PATH_CONTAINS: Final[set[tuple[str, ...]]] = {
    ("docs", "architecture", "prompts"),
}


class Section(StrEnum):
    """High-level repository segment."""

    BACKEND_SERVICE = auto()
    BACKEND_SHARED = auto()
    FRONTEND = auto()
    INFRASTRUCTURE = auto()
    SCRIPTS = auto()
    TESTS_ROOT = auto()
    DOCS = auto()
    ROOT = auto()
    PROMPT_ASSEMBLER = auto()
    OTHER = auto()


class FileKind(StrEnum):
    """File role classification."""

    CODE = auto()
    TEST_CODE = auto()
    DOCS = auto()
    INFRA = auto()
    FRONTEND_ASSET = auto()
    DATA = auto()
    UNKNOWN = auto()


CODE_EXTENSIONS: set[str] = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".cs",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".sql",
    ".proto",
}

DOC_EXTENSIONS: set[str] = {
    ".md",
    ".rst",
    ".adoc",
}

INFRA_EXTENSIONS: set[str] = {
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".hcl",
}

FRONTEND_ASSET_EXTENSIONS: set[str] = {
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
}

DATA_EXTENSIONS: set[str] = {
    ".csv",
    ".tsv",
}

COMMENT_PREFIXES: dict[str, tuple[str, ...]] = {
    ".py": ("#",),
    ".pyi": ("#",),
    ".sh": ("#",),
    ".bash": ("#",),
    ".zsh": ("#",),
    ".ps1": ("#",),
    ".ts": ("//",),
    ".tsx": ("//",),
    ".js": ("//",),
    ".jsx": ("//",),
    ".go": ("//",),
    ".rs": ("//",),
    ".java": ("//",),
    ".kt": ("//",),
    ".c": ("//",),
    ".cc": ("//",),
    ".cpp": ("//",),
    ".cxx": ("//",),
    ".cs": ("//",),
    ".sql": ("--",),
    ".proto": ("//",),
}


# Models


@dataclass(frozen=True, slots=True)
class FileStat:
    """Per-file statistics."""

    path: Path
    section: Section
    kind: FileKind
    loc: int


@dataclass(slots=True)
class Aggregate:
    """Roll-up statistics."""

    files: int = 0
    code_files: int = 0
    tests: int = 0
    code_loc: int = 0
    symbols: int = 0
    classes: int = 0
    functions: int = 0

    def add(self, stat: FileStat) -> None:
        """Add a file stat to the aggregate."""
        self.files += 1
        if stat.kind in (FileKind.CODE, FileKind.TEST_CODE):
            self.code_files += 1
            self.code_loc += stat.loc
        if stat.kind is FileKind.TEST_CODE:
            self.tests += 1


# Helpers


def _is_lockfile(path: Path) -> bool:
    return path.name in LOCKFILE_NAMES or path.suffix == ".lock"


@lru_cache(maxsize=1024)
def _should_skip(path: Path) -> bool:
    """Check if path should be skipped. Uses LRU cache for repeated path checks."""
    if _is_lockfile(path):
        return True
    if (path_parts_set := set(path.parts)) and (path_parts_set & SKIP_DIR_FRAGMENTS):
        return True
    return any(sequence <= path.parts for sequence in SKIP_PATH_CONTAINS)


_SECTION_LOOKUP: Final[dict[str, Section]] = {
    "typescript": Section.FRONTEND,
    "infrastructure": Section.INFRASTRUCTURE,
    "scripts": Section.SCRIPTS,
    "tests": Section.TESTS_ROOT,
    "docs": Section.DOCS,
    "prompt-assembler": Section.PROMPT_ASSEMBLER,
    "": Section.ROOT,
}


def _section_for(path: Path) -> Section:
    """Determine section for a given path."""
    if not path.parts:
        return Section.OTHER
    first, *rest = path.parts
    if first == "backend":
        return Section.BACKEND_SHARED if rest and rest[0] == "shared" else Section.BACKEND_SERVICE
    return _SECTION_LOOKUP.get(first, Section.OTHER)


def _is_test_file(path: Path) -> bool:
    return "tests" in path.parts or path.stem.startswith("test_") or path.stem.endswith("_test")


def _kind_for(path: Path) -> FileKind:
    suffix = path.suffix.lower()
    match suffix:
        case s if s in DOC_EXTENSIONS or Section.DOCS is _section_for(path):
            return FileKind.DOCS
        case s if s in FRONTEND_ASSET_EXTENSIONS:
            return FileKind.FRONTEND_ASSET
        case s if s in INFRA_EXTENSIONS or path.name.lower() in {
            "dockerfile",
            "justfile",
        }:
            return FileKind.INFRA
        case s if s in DATA_EXTENSIONS:
            return FileKind.DATA
        case s if s in CODE_EXTENSIONS:
            return FileKind.TEST_CODE if _is_test_file(path) else FileKind.CODE
        case _:
            return FileKind.UNKNOWN


def _count_loc(path: Path) -> int:
    suffix = path.suffix.lower()
    comment_prefixes = COMMENT_PREFIXES.get(suffix, ())
    loc = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            if line := raw_line.strip():
                if comment_prefixes and any(line.startswith(prefix) for prefix in comment_prefixes):
                    continue
                loc += 1
    return loc


def _git_ls_files(root: Path) -> list[Path]:
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    proc = subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True)
    return [(root / line).resolve() for line in proc.stdout.splitlines() if line.strip()]


def _iter_files(root: Path) -> Iterable[Path]:
    try:
        files = _git_ls_files(root)
    except subprocess.CalledProcessError, FileNotFoundError:
        files = [p for p in root.rglob("*") if p.is_file()]

    for path in files:
        relative = path.relative_to(root)
        if _should_skip(relative) or not (root / relative).exists():
            continue
        yield relative


def _analyze(root: Path) -> list[FileStat]:
    """Analyze all files in the repository with progress indication."""
    files = list(_iter_files(root))
    stats: list[FileStat] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Analyzing {len(files)} files...", total=len(files))

        for relative in files:
            section = _section_for(relative)
            kind = _kind_for(relative)
            loc = _count_loc(root / relative) if kind in (FileKind.CODE, FileKind.TEST_CODE) else 0
            stats.append(FileStat(path=relative, section=section, kind=kind, loc=loc))
            progress.update(task, advance=1)

    return stats


def _aggregate_by_section(stats: Sequence[FileStat]) -> dict[Section, Aggregate]:
    aggregates: dict[Section, Aggregate] = {section: Aggregate() for section in Section}
    for stat in stats:
        aggregates[stat.section].add(stat)
    return aggregates


def _aggregate_by_kind(stats: Sequence[FileStat]) -> dict[FileKind, Aggregate]:
    aggregates: dict[FileKind, Aggregate] = {kind: Aggregate() for kind in FileKind}
    for stat in stats:
        aggregates[stat.kind].add(stat)
    return aggregates


def _analyze_symbols(root: Path) -> dict[str, int] | None:
    """Analyze symbols using ast_explorer if available."""
    try:
        from ast_explorer.analysis.extractor import ASTExtractor
    except ImportError:
        console.print("[yellow]ast_explorer not available, skipping symbol analysis[/yellow]")
        return None

    extractor = ASTExtractor(root)
    codebase = extractor.extract()
    summary = codebase.get_summary()
    return {
        "total_symbols": summary.get("total_symbols", 0),
        "classes": summary.get("class", 0),
        "functions": summary.get("function", 0) + summary.get("async_function", 0),
        "methods": summary.get("method", 0) + summary.get("async_method", 0),
    }


def _print_human(stats: Sequence[FileStat], symbol_stats: dict[str, int] | None = None) -> None:
    """Print analysis results using Rich tables."""
    total_files = len(stats)
    code_stats = [s for s in stats if s.kind in (FileKind.CODE, FileKind.TEST_CODE)]
    total_code_files = sum(1 for s in code_stats if s.loc > 0)
    total_loc = sum(s.loc for s in code_stats)

    console.rule("[bold blue]Repository Scale Analysis[/bold blue]")

    summary_table = Table(show_header=True, header_style="bold cyan")
    summary_table.add_column("Metric")
    summary_table.add_column("Value", justify="right")
    summary_table.add_row("Tracked files", f"{total_files:,}")
    summary_table.add_row("Code files", f"{total_code_files:,}")
    summary_table.add_row("Lines of code", f"{total_loc:,}")

    if symbol_stats:
        summary_table.add_row("Total symbols", f"{symbol_stats['total_symbols']:,}")
        summary_table.add_row("Classes", f"{symbol_stats['classes']:,}")
        summary_table.add_row("Functions", f"{symbol_stats['functions']:,}")
        summary_table.add_row("Methods", f"{symbol_stats['methods']:,}")

    console.print(summary_table)

    console.print("\n[bold]By Section[/bold]")
    section_table = Table(show_header=True, header_style="bold")
    section_table.add_column("Section")
    section_table.add_column("Files", justify="right")
    section_table.add_column("Code", justify="right")
    section_table.add_column("Tests", justify="right")
    section_table.add_column("LOC", justify="right")

    for section, agg in sorted(_aggregate_by_section(stats).items()):
        if agg.files == 0:
            continue
        section_name = section.value.replace("_", " ").title()
        section_table.add_row(
            section_name,
            str(agg.files),
            str(agg.code_files),
            str(agg.tests),
            f"{agg.code_loc:,}",
        )
    console.print(section_table)

    console.print("\n[bold]By Kind[/bold]")
    kind_table = Table(show_header=True, header_style="bold")
    kind_table.add_column("Kind")
    kind_table.add_column("Files", justify="right")
    kind_table.add_column("Code", justify="right")
    kind_table.add_column("Tests", justify="right")
    kind_table.add_column("LOC", justify="right")

    for kind, agg in sorted(_aggregate_by_kind(stats).items()):
        if agg.files == 0:
            continue
        kind_name = kind.value.replace("_", " ").title()
        loc_display = f"{agg.code_loc:,}" if kind in (FileKind.CODE, FileKind.TEST_CODE) else "N/A"
        kind_table.add_row(
            kind_name,
            str(agg.files),
            str(agg.code_files),
            str(agg.tests),
            loc_display,
        )
    console.print(kind_table)


def _print_json(stats: Sequence[FileStat], symbol_stats: dict[str, int] | None = None) -> None:
    code_stats = [s for s in stats if s.kind in (FileKind.CODE, FileKind.TEST_CODE)]
    payload: dict = {
        "total_files": len(stats),
        "total_code_files": sum(1 for s in code_stats if s.loc > 0),
        "total_loc": sum(s.loc for s in code_stats),
        "sections": {
            section.value: vars(aggregate)
            for section, aggregate in _aggregate_by_section(stats).items()
            if aggregate.files > 0
        },
        "kinds": {
            kind.value: vars(aggregate) for kind, aggregate in _aggregate_by_kind(stats).items() if aggregate.files > 0
        },
    }
    if symbol_stats:
        payload["symbols"] = symbol_stats
    typer.echo(json.dumps(payload, indent=2))


app = typer.Typer(
    name="analyze-codebase",
    help="Analyze repository scale (code files and LOC).",
    no_args_is_help=False,
)


@app.command()
def main(
    root: Annotated[
        Path,
        typer.Option("--root", "-r", help="Repository root directory."),
    ] = REPO_ROOT,
    output_json: Annotated[
        bool,
        typer.Option("--json", "-j", help="Emit JSON instead of human-readable text."),
    ] = False,
    with_symbols: Annotated[
        bool,
        typer.Option("--symbols", "-s", help="Include AST symbol counts (requires ast_explorer)."),
    ] = False,
) -> None:
    """Analyze repository scale (code files and LOC)."""
    resolved_root = root.resolve()
    stats = _analyze(resolved_root)

    symbol_stats = None
    if with_symbols:
        symbol_stats = _analyze_symbols(resolved_root)

    if output_json:
        _print_json(stats, symbol_stats)
    else:
        _print_human(stats, symbol_stats)


if __name__ == "__main__":
    app()

"""File discovery and scanning."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Final

DEFAULT_EXCLUDES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
        ".idea",
        ".vscode",
    }
)


class FileScanner:
    """Scans directories for source files.

    Uses git ls-files when available for accurate gitignore handling,
    falling back to directory traversal with pattern matching.
    """

    def __init__(
        self,
        root: Path,
        extensions: frozenset[str],
        excludes: frozenset[str] | None = None,
    ) -> None:
        """Initialize scanner with root path and file extensions to include."""
        self.root = root.resolve()
        self.extensions = extensions
        self.excludes = excludes or DEFAULT_EXCLUDES
        self._exclude_parts: frozenset[str] = frozenset(p for p in self.excludes if not p.startswith("*"))

    def scan(self) -> Iterator[Path]:
        """Scan for source files.

        Yields absolute paths to files matching the configured extensions.
        """
        if self._is_git_repo():
            yield from self._scan_git()
        else:
            yield from self._scan_filesystem()

    def _is_git_repo(self) -> bool:
        """Check if root is inside a git repository."""
        return (self.root / ".git").exists() or any((p / ".git").exists() for p in self.root.parents)

    def _scan_git(self) -> Iterator[Path]:
        """Scan using git ls-files for accurate gitignore handling."""
        cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
        try:
            result = subprocess.run(
                cmd,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError, FileNotFoundError:
            yield from self._scan_filesystem()
            return

        for line in result.stdout.splitlines():
            if (stripped := line.strip()) and self._should_include(path := self.root / stripped):
                yield path

    def _scan_filesystem(self) -> Iterator[Path]:
        """Scan filesystem directly with pattern matching."""
        for ext in self.extensions:
            for path in self.root.rglob(f"*.{ext}"):
                if self._should_include(path):
                    yield path

    def _should_include(self, path: Path) -> bool:
        """Check if a file should be included based on filters."""
        return (
            path.is_file()
            and path.suffix.lstrip(".") in self.extensions
            and not (set(path.relative_to(self.root).parts) & self._exclude_parts)
        )

    def count_files(self) -> int:
        """Count files without yielding them (for progress bars)."""
        return sum(1 for _ in self.scan())

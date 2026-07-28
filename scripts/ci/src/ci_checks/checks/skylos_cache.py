"""Run Skylos with content-addressed grep-verification caching."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

_GREP_CACHE_SCHEMA = "v4"
_SEARCHABLE_SUFFIXES = frozenset(
    {
        ".cjs",
        ".cfg",
        ".dart",
        ".go",
        ".ini",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".md",
        ".mjs",
        ".php",
        ".py",
        ".pyi",
        ".rs",
        ".rst",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".skylos",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
_HASH_CHUNK_BYTES = 1024 * 1024


def _hash_file(path: str | Path) -> str:
    """Hash the complete contents of one file."""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _search_corpus_hash(project_root: Path) -> str:
    """Hash every file that Skylos grep verification can search."""
    digest = hashlib.sha256()
    for directory, directory_names, file_names in os.walk(project_root):
        directory_names[:] = sorted(
            name for name in directory_names if name not in _EXCLUDED_DIRECTORY_NAMES and not name.endswith(".egg-info")
        )
        for file_name in sorted(file_names):
            path = Path(directory, file_name)
            if path.suffix.lower() not in _SEARCHABLE_SUFFIXES:
                continue
            relative = path.relative_to(project_root).as_posix().encode()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            content_hash = _hash_file(path).encode()
            digest.update(len(content_hash).to_bytes(2, "big"))
            digest.update(content_hash)
    return digest.hexdigest()


def _configure_grep_cache(project_root: Path) -> str:
    """Install the sound grep-cache hash and return its namespace."""
    from skylos.core import grep_cache, grep_verify

    namespace = f"{_GREP_CACHE_SCHEMA}:{_search_corpus_hash(project_root)}"
    vars(grep_cache)["file_content_hash"] = _hash_file
    vars(grep_verify)["_GREP_VERIFY_CACHE_VERSION"] = namespace
    return namespace


def main() -> None:
    """Configure the grep cache before transferring control to Skylos."""
    _configure_grep_cache(Path.cwd().resolve())
    from skylos import cli

    cli.main()


if __name__ == "__main__":
    main()

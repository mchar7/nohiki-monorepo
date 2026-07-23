"""Repository file enumeration for content checks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".avi",
        ".bz2",
        ".class",
        ".db",
        ".dll",
        ".dylib",
        ".ear",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp3",
        ".mp4",
        ".npy",
        ".npz",
        ".o",
        ".otf",
        ".pdf",
        ".pickle",
        ".pkl",
        ".png",
        ".pyc",
        ".pyo",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tgz",
        ".ttf",
        ".war",
        ".wasm",
        ".wav",
        ".webp",
        ".woff",
        ".woff2",
        ".xz",
        ".zip",
        ".zst",
    }
)


def tracked_text_files(repo_root: Path) -> tuple[tuple[Path, str], ...]:
    """Read text from the repository's tracked, non-binary files.

    Args:
        repo_root: Root of the Git working tree.

    Returns:
        Repo-relative paths paired with their working-tree text.

    Raises:
        RuntimeError: If Git cannot enumerate the repository index.
    """
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "-z"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError("git ls-files failed: " + message)

    files: list[tuple[Path, str]] = []
    for encoded_path in completed.stdout.split(b"\0"):
        if not encoded_path:
            continue
        relative = Path(os.fsdecode(encoded_path))
        if relative.suffix.lower() in _BINARY_SUFFIXES:
            continue
        path = repo_root / relative
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        files.append((relative, text))
    return tuple(files)

"""Portable path resolution for Nohiki monorepo tests.

Uses PROJECT_ROOT env var (set by direnv/.envrc) when available,
falling back to uv workspace marker file discovery.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path


@cache
def get_repo_root() -> Path:
    """Resolve the monorepo root directory.

    Uses PROJECT_ROOT env var when available, falling back to
    walking up the directory tree looking for a root pyproject.toml
    with [tool.uv.workspace].

    Returns:
        Absolute path to the monorepo root directory.

    Raises:
        FileNotFoundError: If PROJECT_ROOT is unset and no root
            pyproject.toml with [tool.uv.workspace] is found.
    """
    if root := os.environ.get("PROJECT_ROOT"):
        return Path(root)

    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file() and "[tool.uv.workspace]" in pyproject.read_text():
            return parent

    msg = (
        "Could not find monorepo root. Set PROJECT_ROOT or ensure root pyproject.toml with [tool.uv.workspace] exists."
    )
    raise FileNotFoundError(msg)


def get_test_secrets_dir() -> Path:
    """Get the path to the shared test secrets directory.

    Returns:
        Absolute path to the secrets directory.
    """
    return get_repo_root() / "infra" / "shared" / "secrets"

"""Path discovery helpers.

``get_repo_root`` walks upward from the current package looking for the
``[tool.uv.workspace]`` table in ``pyproject.toml``. ``PROJECT_ROOT`` environment
variable overrides the search when set, supporting tests that operate on
sandbox copies of the repository.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_repo_root() -> Path:
    """Return the monorepo root.

    Priority order:
    1. ``PROJECT_ROOT`` env var (absolute path)
    2. Nearest ancestor of this module containing ``pyproject.toml`` with ``[tool.uv.workspace]``
    """
    env = os.environ.get("PROJECT_ROOT")
    if env:
        candidate = Path(env).resolve()
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file() and "[tool.uv.workspace]" in pyproject.read_text():
            return parent
    msg = "Could not locate repo root (no pyproject.toml with [tool.uv.workspace] found)"
    raise RuntimeError(msg)

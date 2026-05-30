"""Re-exports of canonical ``[build-system]`` constants from ``ci_checks``.

The build-backend canonicalization rule lives in
``scripts/ci/src/ci_checks/checks/build_backend.py``. Importing from there
at render time guarantees scaffolded ``pyproject.toml`` files never
drift from the hygiene check that gates the CI pipeline.
"""

from __future__ import annotations

from ci_checks.checks.build_backend import CANONICAL_BUILD_BACKEND, CANONICAL_REQUIRES

__all__ = [
    "CANONICAL_BUILD_BACKEND",
    "CANONICAL_REQUIRES",
    "canonical_build_system_block",
]


def canonical_build_system_block() -> str:
    """Return the canonical ``[build-system]`` TOML block as a string.

    The returned value is suitable for embedding verbatim inside a
    rendered ``pyproject.toml`` (no trailing blank line).
    """
    requires_list = ", ".join(f'"{r}"' for r in CANONICAL_REQUIRES)
    return f'[build-system]\nrequires = [{requires_list}]\nbuild-backend = "{CANONICAL_BUILD_BACKEND}"\n'

"""Fixtures for scaffold integration tests.

The ``tmp_repo`` fixture builds a minimal monorepo-shaped pyproject in a
tmpdir. It does not copy real workspace libs because the tests exercise
plan/apply behaviour and root pyproject edits, not ``uv sync`` execution.
Tests that need a real installable workspace are explicitly marked as
``slow`` and gated behind the presence of ``uv`` on ``PATH``.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

_MINIMAL_PYPROJECT = dedent(
    """\
    [project]
    name = "nohiki-monorepo"
    version = "0.0.0"
    requires-python = ">=3.14"

    [tool.uv.workspace]
    members = [
        # Shared libraries
        # CLI tools (only add when needed as dependencies by other packages)
    ]

    [tool.uv.sources]

    [tool.ty.environment]
    python-version = "3.14"
    root = [
        # Scripts (flat layout - parent directory is the source root)
    ]
    """,
)


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Return a tmpdir populated with a minimal pyproject and empty backend tree."""
    (tmp_path / "pyproject.toml").write_text(_MINIMAL_PYPROJECT, encoding="utf-8")
    (tmp_path / "backend" / "libs").mkdir(parents=True)
    (tmp_path / "backend" / "services").mkdir(parents=True)
    return tmp_path

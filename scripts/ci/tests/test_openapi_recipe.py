from __future__ import annotations

import shlex
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "Justfile"


def test_api_schema_check_uses_frozen_all_workspace_environment() -> None:
    """OpenAPI export must retain every installed workspace runtime dependency."""
    commands = [
        shlex.split(line.strip())
        for line in _JUSTFILE.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("uv run ") and "scripts/util/export-openapi.py" in line
    ]

    assert len(commands) == 1, "api-schema-check must define exactly one OpenAPI export command"
    assert commands[0][:6] == [
        "uv",
        "run",
        "--frozen",
        "--all-packages",
        "python",
        "scripts/util/export-openapi.py",
    ]

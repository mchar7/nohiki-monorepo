from __future__ import annotations

import shlex
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "Justfile"


def test_api_schema_check_reuses_the_authoritative_workspace_environment() -> None:
    """OpenAPI export must not resynchronize (and thereby narrow) the pre-built workspace env."""
    commands = [
        shlex.split(line.strip().split(" -- ", 1)[-1])
        for line in _JUSTFILE.read_text(encoding="utf-8").splitlines()
        if "uv run " in line and "scripts/util/export-openapi.py" in line
    ]

    assert len(commands) == 1, "api-schema-check must define exactly one OpenAPI export command"
    assert commands[0][:5] == [
        "uv",
        "run",
        "--no-sync",
        "python",
        "scripts/util/export-openapi.py",
    ]

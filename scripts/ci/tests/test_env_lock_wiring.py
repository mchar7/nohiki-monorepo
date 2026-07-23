"""Contract checks for environment-mutating and environment-consuming commands."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_LOCK_WRAPPER = "scripts/dev/env-lock.sh"
_LOCK_INVOCATION = (f"{_LOCK_WRAPPER} ", "{{ env_lock }} ")
_DEV_SYNC_SHAPE = "--all-packages --all-extras --no-extra cuda --group deadcode"


def _runs(value: object) -> list[str]:
    if isinstance(value, Mapping):
        runs: list[str] = []
        for key, item in value.items():
            if key == "run" and isinstance(item, str):
                runs.append(item)
            else:
                runs.extend(_runs(item))
        return runs
    if isinstance(value, list):
        return [run for item in value for run in _runs(item)]
    return []


def test_lefthook_environment_commands_use_shared_locks() -> None:
    config = yaml.safe_load((_ROOT / "lefthook.yml").read_text(encoding="utf-8"))

    for command in _runs(config):
        if "uv run" in command:
            assert f"{_LOCK_WRAPPER} shared venv --" in command
            assert "uv run --no-sync" in command
        if "pnpm" in command:
            assert f"{_LOCK_WRAPPER} shared node_modules --" in command


def test_justfile_environment_commands_use_mode_matching_locks() -> None:
    commands = [
        line.strip()
        for line in (_ROOT / "Justfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("    ") and not line.lstrip().startswith("#")
    ]

    sync_commands = [command for command in commands if "uv sync" in command]
    assert sync_commands
    for command in sync_commands:
        assert any(f"{invocation}exclusive venv --" in command for invocation in _LOCK_INVOCATION)

    for command in commands:
        if "uv run" in command:
            assert any(f"{invocation}shared venv --" in command for invocation in _LOCK_INVOCATION)
            assert "uv run --no-sync" in command
        if "pnpm" in command:
            assert any(f"{invocation}shared node_modules --" in command for invocation in _LOCK_INVOCATION)


def test_development_sync_shape_is_identical() -> None:
    justfile = (_ROOT / "Justfile").read_text(encoding="utf-8")
    flake = (_ROOT / "flake.nix").read_text(encoding="utf-8")
    just_syncs = [line for line in justfile.splitlines() if "uv sync" in line]
    flake_syncs = [line for line in flake.splitlines() if "uv sync" in line and _DEV_SYNC_SHAPE in line]

    assert len(just_syncs) == 2
    assert len(flake_syncs) == 1
    assert all(_DEV_SYNC_SHAPE in line for line in [*just_syncs, *flake_syncs])
    assert "--locked" in flake_syncs[0]


def test_nested_lock_invocation_is_reentrant() -> None:
    wrapper = _ROOT / "scripts" / "dev" / "env-lock.sh"
    result = subprocess.run(
        [
            "timeout",
            "10",
            str(wrapper),
            "shared",
            "venv",
            "--",
            str(wrapper),
            "exclusive",
            "venv",
            "--",
            "true",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
    assert result.stderr == ""

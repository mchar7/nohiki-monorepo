from __future__ import annotations

import shlex
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_LEFTHOOK = _ROOT / "lefthook.yml"


def _uv_run_invocations(node: object) -> Iterator[str]:
    """Yield each uv run invocation nested in hook command fields."""
    if isinstance(node, Mapping):
        for key, child in node.items():
            if key == "run" and isinstance(child, str):
                command = child.strip()
                tokens = shlex.split(command)
                for index in range(len(tokens) - 1):
                    if tokens[index : index + 2] == ["uv", "run"]:
                        yield command
            else:
                yield from _uv_run_invocations(child)
    elif isinstance(node, list):
        for child in node:
            yield from _uv_run_invocations(child)


def _named_mappings(node: object, name: str) -> Iterator[Mapping[str, object]]:
    if isinstance(node, Mapping):
        if node.get("name") == name:
            yield node
        for child in node.values():
            yield from _named_mappings(child, name)
    elif isinstance(node, list):
        for child in node:
            yield from _named_mappings(child, name)


def _has_no_sync_after_every_run(command: str) -> bool:
    tokens = shlex.split(command)
    return all(
        tokens[index : index + 3] == ["uv", "run", "--no-sync"]
        for index in range(len(tokens) - 1)
        if tokens[index : index + 2] == ["uv", "run"]
    )


@pytest.fixture(scope="module")
def lefthook_config() -> Mapping[str, object]:
    config = yaml.safe_load(_LEFTHOOK.read_text(encoding="utf-8"))
    assert isinstance(config, Mapping)
    return config


def test_hook_uv_runs_reuse_the_authoritative_workspace_environment(
    lefthook_config: Mapping[str, object],
) -> None:
    """Hook phases must not resynchronize the shared all-workspace .venv."""
    config = lefthook_config
    python_test_jobs = tuple(_named_mappings(config.get("pre-push"), "python-tests"))
    assert len(python_test_jobs) == 1, "pre-push must define exactly one python-tests job"
    python_tests_env = python_test_jobs[0].get("env")
    assert isinstance(python_tests_env, Mapping)
    assert python_tests_env.get("UV_NO_SYNC") == "1"

    commands = tuple(
        command for hook in ("pre-commit", "pre-push") for command in _uv_run_invocations(config.get(hook))
    )
    assert commands, "pre-commit and pre-push must contain at least one uv run command"

    violations = tuple(command for command in commands if not _has_no_sync_after_every_run(command))
    assert not violations, (
        "hook uv run commands must put --no-sync immediately after run; "
        f"found {len(violations)} violating command(s):\n" + "\n".join(f"- {command}" for command in violations)
    )


def test_pre_push_folds_fixture_gate_into_the_single_python_test_job(
    lefthook_config: Mapping[str, object],
) -> None:
    pre_push = lefthook_config.get("pre-push")

    assert not tuple(_named_mappings(pre_push, "fixtures"))
    python_test_jobs = tuple(_named_mappings(pre_push, "python-tests"))
    assert len(python_test_jobs) == 1
    assert "--unused-fixtures" not in str(python_test_jobs[0]["run"])

    semgrep_jobs = tuple(_named_mappings(pre_push, "semgrep"))
    assert len(semgrep_jobs) == 1
    assert str(semgrep_jobs[0]["run"]).startswith("env -u LD_LIBRARY_PATH uvx ")

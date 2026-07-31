from __future__ import annotations

import shlex
import subprocess
import tomllib
from collections.abc import Iterator, Mapping
from itertools import takewhile
from pathlib import Path, PurePosixPath

import pytest
from _documents import load_mapping
from ci_checks.core.packages import REPO_ROOT, Scope, load_packages

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


def _named_mappings(node: object, name: str) -> Iterator[object]:
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
    return load_mapping(_LEFTHOOK)


def test_hook_uv_runs_reuse_the_authoritative_workspace_environment(
    lefthook_config: Mapping[str, object],
) -> None:
    """Hook phases must not resynchronize the shared all-workspace .venv."""
    config = lefthook_config
    python_test_jobs = tuple(_named_mappings(config.get("pre-push"), "python-tests"))
    assert len(python_test_jobs) == 1, "pre-push must define exactly one python-tests job"
    python_test_job = python_test_jobs[0]
    assert isinstance(python_test_job, Mapping)
    python_tests_env = python_test_job.get("env")
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
    python_test_job = python_test_jobs[0]
    assert isinstance(python_test_job, Mapping)
    python_test_command = python_test_job.get("run")
    assert isinstance(python_test_command, str)
    assert "--unused-fixtures" not in python_test_command

    semgrep_jobs = tuple(_named_mappings(pre_push, "semgrep"))
    assert len(semgrep_jobs) == 1
    semgrep_job = semgrep_jobs[0]
    assert isinstance(semgrep_job, Mapping)
    semgrep_command = semgrep_job.get("run")
    assert isinstance(semgrep_command, str)
    assert semgrep_command == "just hygiene-arch"


def test_pre_push_rejects_unformatted_python(lefthook_config: Mapping[str, object]) -> None:
    command = _run_command(_sole_job(lefthook_config, "python-format"))
    probe = _ROOT / "pre_push_format_regression.py"
    assert not probe.exists()
    try:
        probe.write_text("VALUE=  1\n", encoding="utf-8")
        failed = subprocess.run(
            shlex.split(command),
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert failed.returncode != 0
        assert "Would reformat" in failed.stdout
    finally:
        probe.unlink(missing_ok=True)

    passed = subprocess.run(
        shlex.split(command),
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert passed.returncode == 0, passed.stdout + passed.stderr


def _glob_entries(node: object) -> set[str] | None:
    """Return the glob patterns a lefthook job declares, or None when it is unconditional."""
    assert isinstance(node, Mapping)
    raw = node.get("glob")
    if raw is None:
        return None
    if isinstance(raw, str):
        return {raw}
    assert isinstance(raw, list)
    return {entry for entry in raw if isinstance(entry, str)}


def _sole_job(config: Mapping[str, object], name: str) -> object:
    """Return the single lefthook job declaring the given name."""
    jobs = tuple(_named_mappings(config, name))
    assert len(jobs) == 1, f"lefthook must declare exactly one {name} job"
    return jobs[0]


def _run_command(node: object) -> str:
    """Return the shell command a lefthook job runs."""
    assert isinstance(node, Mapping)
    command = node.get("run")
    assert isinstance(command, str)
    return command


def _workspace_python_roots() -> tuple[PurePosixPath, ...]:
    """Repo-relative directory of every workspace package the hosted lanes scan.

    The hosted Typecheck backend step resolves PACKAGE_SCOPE=ALL to the editable
    source path of each workspace member, which is what require_src selects here.
    """
    return tuple(
        PurePosixPath(pkg.path.relative_to(REPO_ROOT).as_posix()) for pkg in load_packages(Scope.ALL, require_src=True)
    )


def _globs_cover(root: PurePosixPath, patterns: set[str]) -> bool:
    """Whether any pattern selects Python files anywhere under a package root."""
    probes = (root / "module.py", root / "src" / "package" / "module.py")
    return all(any(probe.full_match(pattern) for pattern in patterns) for probe in probes)


def _ty_check_roots(command: str) -> tuple[PurePosixPath, ...]:
    """Return the native ty source roots reached by the delegated command."""
    if command.strip() == "just typecheck-all":
        config = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return tuple(PurePosixPath(path) for path in config["tool"]["ty"]["src"]["include"])

    tokens = shlex.split(command)
    starts = [index + 2 for index in range(len(tokens) - 1) if tokens[index : index + 2] == ["ty", "check"]]
    assert len(starts) == 1, "python-typecheck must invoke ty check exactly once"
    return tuple(
        PurePosixPath(token) for token in takewhile(lambda token: not token.startswith("-"), tokens[starts[0] :])
    )


def test_python_push_lanes_cover_every_workspace_package(
    lefthook_config: Mapping[str, object],
) -> None:
    """Push lanes must trigger on, and scan, every Python package the workspace declares.

    Comparing the lanes against each other cannot see a package that is missing from
    all of them, so the workspace manifest is the reference: a new package directory
    fails this test on the day it is added. The affected-test lane satisfies the same
    guarantee by carrying no glob at all, which reaches every package by construction.
    """
    roots = _workspace_python_roots()
    assert roots, "workspace manifest declares no Python packages"

    # `ci-checks tests affected --mode push` owns package selection, including the seeds
    # no extension glob can express. Any glob here is a partial second copy of that
    # policy, so the lane covers every package only while it stays unconditional.
    assert _glob_entries(_sole_job(lefthook_config, "python-tests")) is None, (
        "python-tests must stay unconditional; a glob narrows the affected-package closure"
    )

    for lane in ("python-typecheck", "deadcode", "deptry"):
        patterns = _glob_entries(_sole_job(lefthook_config, lane))
        assert patterns is not None, f"{lane} is glob-gated and must declare its trigger surface"
        missing = sorted(str(root) for root in roots if not _globs_cover(root, patterns))
        assert not missing, f"{lane} globs skip workspace packages: {missing}"

    scanned = _ty_check_roots(_run_command(_sole_job(lefthook_config, "python-typecheck")))
    assert scanned, "python-typecheck must pass at least one path to ty check"
    unscanned = sorted(str(root) for root in roots if not any(root.is_relative_to(arg) for arg in scanned))
    assert not unscanned, f"ty check arguments skip workspace packages: {unscanned}"

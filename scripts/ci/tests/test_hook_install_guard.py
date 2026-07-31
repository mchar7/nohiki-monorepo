"""The supported hook install path must not overwrite a hardened wrapper.

Lefthook's installer replaces git hooks unconditionally. On a workstation that
installs a hardened wrapper, that silently downgrades every hook to an
unverified shim and drops the digest checks. That happened once already, so the
behaviour is pinned here.

A marker string is only a hint. When hooks look hardened, the wrapper's own
verifier decides, and an unavailable or failing verifier fails closed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "dev" / "install-hooks.sh"
_SENTINEL = "installed-by-lefthook"


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    return repository


def _fake_installer(tmp_path: Path) -> list[str]:
    """Stands in for `lefthook install`, stamping any hook it overwrites."""
    installer = tmp_path / "fake-lefthook.sh"
    installer.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'hooks="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"\n'
        'mkdir -p "$hooks"\n'
        f'printf "{_SENTINEL}\\n" > "$hooks/pre-push"\n',
        encoding="utf-8",
    )
    installer.chmod(0o755)
    return [str(installer)]


def _fake_guard(tmp_path: Path, *, passes: bool) -> Path:
    guard = tmp_path / "fake-guard.sh"
    guard.write_text(f"#!/usr/bin/env bash\nexit {0 if passes else 1}\n", encoding="utf-8")
    guard.chmod(0o755)
    return guard


def _run(repository: Path, command: list[str], guard: Path | None) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"HOME": str(repository.parent)}
    env["NOHIKI_REFERENCE_GUARD"] = str(guard) if guard is not None else str(repository / "absent")
    return subprocess.run(
        [str(_SCRIPT), *command],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _harden(repository: Path, hook: str) -> None:
    hooks = repository / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / hook).write_text("#!/bin/sh\nverify_hash() { :; }\n", encoding="utf-8")


def _pre_push(repository: Path) -> str:
    path = repository / ".git" / "hooks" / "pre-push"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_fresh_clone_installs_normally(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    result = _run(repository, _fake_installer(tmp_path), None)

    assert result.returncode == 0, result.stderr
    assert _pre_push(repository).strip() == _SENTINEL


@pytest.mark.parametrize("hook", ["pre-commit", "commit-msg", "pre-push"])
def test_verified_wrapper_is_left_alone(tmp_path: Path, hook: str) -> None:
    repository = _repository(tmp_path)
    _harden(repository, hook)
    before = _pre_push(repository)

    result = _run(repository, _fake_installer(tmp_path), _fake_guard(tmp_path, passes=True))

    assert result.returncode == 0, result.stderr
    assert _pre_push(repository) == before
    assert _SENTINEL not in _pre_push(repository)


def test_failing_verifier_fails_closed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _harden(repository, "pre-push")
    before = _pre_push(repository)

    result = _run(repository, _fake_installer(tmp_path), _fake_guard(tmp_path, passes=False))

    assert result.returncode == 1
    assert "fail verification" in result.stderr
    assert _pre_push(repository) == before


def test_absent_verifier_fails_closed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _harden(repository, "pre-push")
    before = _pre_push(repository)

    result = _run(repository, _fake_installer(tmp_path), tmp_path / "does-not-exist")

    assert result.returncode == 1
    assert "no verifier is available" in result.stderr
    assert _pre_push(repository) == before


def test_already_clobbered_hooks_are_not_reinstalled_when_a_verifier_exists(tmp_path: Path) -> None:
    """Already-clobbered hooks carry no marker, so a marker scan reads them as a fresh clone."""
    repository = _repository(tmp_path)
    hooks = repository / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text("#!/bin/sh\n# plain lefthook shim\n", encoding="utf-8")
    before = _pre_push(repository)

    result = _run(repository, _fake_installer(tmp_path), _fake_guard(tmp_path, passes=False))

    assert result.returncode == 1
    assert "fail verification" in result.stderr
    assert _pre_push(repository) == before
    assert _SENTINEL not in _pre_push(repository)


def test_the_supported_recipe_routes_through_this_guard() -> None:
    justfile = Path(__file__).resolve().parents[3] / "Justfile"
    recipe = justfile.read_text(encoding="utf-8").split("hooks-install:", 1)[1].splitlines()[1]

    assert "install-hooks.sh" in recipe, recipe
    assert "lefthook install" in recipe, recipe

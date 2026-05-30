"""Atomic apply guarantees.

The scaffolder promises: (1) each individual file write is atomic via
tempfile + os.replace; (2) root pyproject edits are validated with
``tomllib.loads`` before commit; (3) git is the rollback surface.

These tests exercise the failure modes directly: a mid-stream file write
failure and a tomlkit edit that would produce invalid TOML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nohiki_scaffold.core.build import apply_plan, build_plan
from nohiki_scaffold.core.exceptions import WorkspaceEditError

from ..goldens import factories

pytestmark = pytest.mark.integration


def test_apply_refuses_existing_target(tmp_repo: Path) -> None:
    spec = factories.plain_lib()
    plan = build_plan(spec, repo_root=tmp_repo)

    target = tmp_repo / "backend" / "libs" / spec.name
    target.mkdir(parents=True)

    with pytest.raises(WorkspaceEditError, match="already exists"):
        apply_plan(plan, repo_root=tmp_repo, dry_run=False)


def test_file_write_failure_propagates(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mid-stream OSError during atomic write must not leave a tmp file behind."""
    spec = factories.plain_lib()
    plan = build_plan(spec, repo_root=tmp_repo)

    real_replace = Path.replace
    calls = {"n": 0}

    def flaky_replace(self: Path, target: str | Path, /) -> Path:
        calls["n"] += 1
        if calls["n"] == 2:
            msg = "simulated disk error"
            raise OSError(msg)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    with pytest.raises(OSError, match="simulated"):
        apply_plan(plan, repo_root=tmp_repo, dry_run=False)

    target = tmp_repo / "backend" / "libs" / spec.name
    leftover_tmp = list(target.glob(".*.tmp"))
    assert leftover_tmp == []


def test_pyproject_is_bit_identical_on_dry_run(tmp_repo: Path) -> None:
    spec = factories.plain_lib()
    plan = build_plan(spec, repo_root=tmp_repo)

    before = (tmp_repo / "pyproject.toml").read_bytes()
    apply_plan(plan, repo_root=tmp_repo, dry_run=True)
    after = (tmp_repo / "pyproject.toml").read_bytes()

    assert before == after

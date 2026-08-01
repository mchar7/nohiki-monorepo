"""Require every Git-tracked symlink to be a filesystem symlink."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def _unmaterialized_symlinks(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    tracked_symlinks = (
        Path(os.fsdecode(record.split(b"\t", 1)[1]))
        for record in result.stdout.split(b"\0")
        if record.startswith(b"120000 ")
    )
    return tuple(path for path in tracked_symlinks if not (root / path).is_symlink())


def test_tracked_symlinks_are_materialized() -> None:
    unmaterialized = _unmaterialized_symlinks(_ROOT)
    checkout_command = shlex.join(["git", "checkout", "--", *(str(path) for path in unmaterialized)])

    assert not unmaterialized, (
        "Git tracks these paths as symlinks, but this checkout materialized them as regular files:\n"
        + "\n".join(f"  {path}" for path in unmaterialized)
        + "\nEnable symlink materialization and re-checkout those paths:\n"
        + "  git config core.symlinks true\n"
        + f"  {checkout_command}"
    )


def test_materialization_check_accepts_a_real_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    (repository / "target.json").write_text("{}\n", encoding="utf-8")
    (repository / "dashboard.json").symlink_to("target.json")
    subprocess.run(["git", "add", "dashboard.json"], cwd=repository, check=True)

    assert _unmaterialized_symlinks(repository) == ()

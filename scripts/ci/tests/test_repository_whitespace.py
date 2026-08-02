"""Guard the complete candidate tree against Git whitespace diagnostics."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_GIT = shutil.which("git") or "git"


def _git_environment(index: Path | None = None) -> dict[str, str]:
    """Return Git settings that cannot inherit a developer's config."""
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    return environment


def _resolve_git_dir(root: Path) -> Path:
    """Resolve the repository git directory from an explicitly anchored root."""
    result = subprocess.run(
        [_GIT, "-C", str(root), "rev-parse", "--absolute-git-dir"],
        cwd=root,
        env=_git_environment(),
        capture_output=True,
        check=True,
    )
    lines = result.stdout.decode("utf-8").splitlines()
    if len(lines) != 1 or not lines[0]:
        assert len(lines) == 1, "Git returned an invalid absolute git directory"
        assert lines[0], "Git returned an invalid absolute git directory"
    git_dir = Path(lines[0])
    if not git_dir.is_absolute() or not git_dir.is_dir():
        assert git_dir.is_absolute(), "Git returned a non-directory absolute git directory"
        assert git_dir.is_dir(), "Git returned a non-directory absolute git directory"
    return git_dir


_GIT_DIR = _resolve_git_dir(_ROOT)


def _git(
    *arguments: str,
    git_dir: Path | None = _GIT_DIR,
    work_tree: Path | None = _ROOT,
    cwd: Path = _ROOT,
    environment: dict[str, str] | None = None,
    check: bool = True,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run Git with an explicit repository, never ambient repository discovery."""
    command = [_GIT]
    if git_dir is not None:
        command.extend(("--git-dir", str(git_dir)))
    if work_tree is not None:
        command.extend(("--work-tree", str(work_tree)))
    command.extend(arguments)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment or _git_environment(),
        input=input_data,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") or "(no stderr)"
        message = f"Git exited {result.returncode}: {stderr}"
        raise AssertionError(message)
    return result


def test_candidate_tree_has_no_git_whitespace_diagnostics() -> None:
    """Check the committed candidate without reading shared mutable state."""
    result = _git(
        "diff",
        "--check",
        _EMPTY_TREE,
        "HEAD",
        "--",
        work_tree=None,
        check=False,
    )

    diagnostics = result.stdout + result.stderr
    assert result.returncode == 0, diagnostics.decode("utf-8", errors="replace")


def test_git_failure_surfaces_stderr() -> None:
    """Include Git's diagnostic when a checked command fails."""
    with pytest.raises(AssertionError, match="definitely-not-a-command"):
        _git("definitely-not-a-command", work_tree=None)


def test_whitespace_diagnostics_follow_git_attributes_and_reject_defects(
    tmp_path: Path,
) -> None:
    """Ignore only the exact vendored artifact while rejecting other defects."""
    repository = tmp_path / "repository"
    (repository / "infra/k8s/gitops/gateway-api-crds").mkdir(parents=True)
    _git(
        "init",
        "--quiet",
        "--initial-branch=main",
        str(repository),
        git_dir=None,
        work_tree=None,
    )
    vendored_relative = Path("infra/k8s/gitops/gateway-api-crds/gateway-api-crds.yaml")
    (repository / ".gitattributes").write_text(
        f"{vendored_relative.as_posix()} -whitespace\n",
        encoding="utf-8",
    )
    vendored_bytes = (_ROOT / vendored_relative).read_bytes()
    (repository / vendored_relative).write_bytes(vendored_bytes)
    sibling = repository / vendored_relative.with_name("gateway-api-crds-sibling.yaml")
    sibling.write_bytes(vendored_bytes + b"bad trailing space  \n")
    (repository / "candidate.txt").write_bytes(b"bad trailing space  \n")
    (repository / "excess-eof-blank-lines.txt").write_bytes(b"clean\n\n\n")

    git_dir = _resolve_git_dir(repository)
    alternate_index = tmp_path / "alternate-index"
    environment = _git_environment(alternate_index)
    _git(
        "add",
        "--all",
        cwd=repository,
        git_dir=git_dir,
        work_tree=repository,
        environment=environment,
    )
    diagnostics = _git(
        "diff",
        "--cached",
        "--check",
        _EMPTY_TREE,
        "--",
        cwd=repository,
        git_dir=git_dir,
        work_tree=tmp_path / "empty-work-tree",
        environment=environment,
        check=False,
    )

    output = diagnostics.stdout + diagnostics.stderr
    assert diagnostics.returncode != 0
    assert b"candidate.txt:1: trailing whitespace" in output
    assert b"gateway-api-crds-sibling.yaml" in output
    assert b"excess-eof-blank-lines.txt" in output
    assert b"new blank line at EOF" in output
    assert vendored_relative.as_posix().encode() not in output

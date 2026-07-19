"""Guard the complete candidate tree against Git whitespace diagnostics."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

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
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment or _git_environment(),
        input=input_data,
        capture_output=True,
        check=check,
    )


def _candidate_index(
    index: Path,
    *,
    git_dir: Path = _GIT_DIR,
    work_tree: Path = _ROOT,
) -> None:
    """Materialize HEAD plus all visible working-tree intent into an alternate index."""
    environment = _git_environment(index)
    _git(
        "read-tree",
        "HEAD",
        git_dir=git_dir,
        work_tree=work_tree,
        cwd=work_tree,
        environment=environment,
    )
    _git(
        "add",
        "--all",
        "--",
        ".",
        git_dir=git_dir,
        work_tree=work_tree,
        cwd=work_tree,
        environment=environment,
    )


def _whitespace_diagnostics(
    index: Path,
    work_tree: Path,
    *,
    git_dir: Path = _GIT_DIR,
    cwd: Path = _ROOT,
) -> bytes:
    """Return raw ``git diff --check`` diagnostics for an alternate candidate index."""
    result = _git(
        "diff",
        "--cached",
        "--check",
        _EMPTY_TREE,
        "--",
        git_dir=git_dir,
        work_tree=work_tree,
        cwd=cwd,
        environment=_git_environment(index),
        check=False,
    )
    return result.stdout + result.stderr


def test_candidate_tree_has_no_git_whitespace_diagnostics(tmp_path: Path) -> None:
    """Check the pre-commit candidate, without changing the real index."""
    real_index = _GIT_DIR / "index"
    real_index_before = real_index.read_bytes()
    candidate_index = tmp_path / "candidate-index"
    _candidate_index(candidate_index)

    # Check the alternate index from an empty work tree so diagnostics are
    # calculated against candidate blobs rather than mutable local file contents.
    diagnostics = _whitespace_diagnostics(candidate_index, tmp_path / "empty-work-tree")

    assert diagnostics == b"", diagnostics.decode("utf-8", errors="replace")
    assert real_index.read_bytes() == real_index_before


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
    sibling.write_bytes(vendored_bytes)
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


def test_whitespace_helpers_support_linked_worktree_gitfile(tmp_path: Path) -> None:
    """Exercise candidate-index and diagnostics helpers through a worktree gitfile."""
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(
        "init",
        "--quiet",
        "--initial-branch=main",
        str(repository),
        git_dir=None,
        work_tree=None,
    )
    (repository / "tracked.txt").write_bytes(b"clean\n")
    commit_environment = _git_environment() | {
        "GIT_AUTHOR_EMAIL": "whitespace-test@example.invalid",
        "GIT_AUTHOR_NAME": "Whitespace Test",
        "GIT_COMMITTER_EMAIL": "whitespace-test@example.invalid",
        "GIT_COMMITTER_NAME": "Whitespace Test",
    }
    _git(
        "add",
        "--all",
        cwd=repository,
        git_dir=repository / ".git",
        work_tree=repository,
        environment=commit_environment,
    )
    _git(
        "commit",
        "--quiet",
        "--message",
        "initial",
        cwd=repository,
        git_dir=repository / ".git",
        work_tree=repository,
        environment=commit_environment,
    )

    linked_worktree = tmp_path / "linked-worktree"
    _git(
        "worktree",
        "add",
        "--quiet",
        "--detach",
        str(linked_worktree),
        "HEAD",
        cwd=repository,
        git_dir=repository / ".git",
        work_tree=repository,
        environment=commit_environment,
    )
    (linked_worktree / "candidate.txt").write_bytes(b"bad trailing space  \n")

    linked_git_dir = _resolve_git_dir(linked_worktree)
    assert (linked_worktree / ".git").is_file()
    real_index = linked_git_dir / "index"
    real_index_before = real_index.read_bytes()
    candidate_index = tmp_path / "linked-candidate-index"

    _candidate_index(
        candidate_index,
        git_dir=linked_git_dir,
        work_tree=linked_worktree,
    )
    diagnostics = _whitespace_diagnostics(
        candidate_index,
        tmp_path / "empty-work-tree",
        git_dir=linked_git_dir,
        cwd=linked_worktree,
    )

    assert b"candidate.txt:1: trailing whitespace" in diagnostics
    assert real_index.read_bytes() == real_index_before

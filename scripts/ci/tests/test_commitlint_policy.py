from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_TYPESCRIPT = _ROOT / "typescript"
_COMMIT_MESSAGE_CORPUS = (
    ("fix(k8s): accept an established alphanumeric scope", True),
    ("fix(s3-client): accept a hyphenated alphanumeric scope", True),
    ("docs: accept a message without a scope", True),
    ("fix(K8s): reject upper-case scope characters", False),
    ("fix(k8s_api): reject underscore separators", False),
    ("feature(k8s): reject an unknown type", False),
)


def _lint(subject: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pnpm", "exec", "commitlint"],
        input=subject,
        cwd=_TYPESCRIPT,
        capture_output=True,
        text=True,
        check=False,
    )


def _lint_edit(subject: str, message_path: Path) -> subprocess.CompletedProcess[str]:
    message_path.write_text(f"{subject}\n", encoding="utf-8")
    return subprocess.run(
        [
            str(_ROOT / "scripts/dev/env-lock.sh"),
            "shared",
            "node_modules",
            "--",
            "pnpm",
            "exec",
            "commitlint",
            "--edit",
            str(message_path),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _lint_range(subject: str) -> subprocess.CompletedProcess[str]:
    commit = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Commitlint parity",
            "-c",
            "user.email=commitlint@example.invalid",
            "commit-tree",
            "HEAD^{tree}",
            "-p",
            "HEAD",
            "-F",
            "-",
        ],
        input=f"{subject}\n",
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return subprocess.run(
        ["pnpm", "exec", "commitlint", "--from", "HEAD", "--to", commit, "--verbose"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.requires_node_modules
def test_local_edit_and_hosted_range_paths_agree_on_one_corpus(tmp_path: Path) -> None:
    for index, (subject, expected) in enumerate(_COMMIT_MESSAGE_CORPUS):
        local = _lint_edit(subject, tmp_path / f"message-{index}")
        hosted = _lint_range(subject)
        evidence = f"\nlocal:\n{local.stdout}{local.stderr}\nhosted:\n{hosted.stdout}{hosted.stderr}"

        assert (local.returncode == 0) is expected, subject + evidence
        assert (hosted.returncode == 0) is expected, subject + evidence


@pytest.mark.requires_node_modules
@pytest.mark.parametrize(
    "subject",
    [
        "Merge branch 'main' into topic",
        "Merge remote-tracking branch 'origin/main' into topic",
    ],
)
def test_integration_merge_subjects_are_ignored(subject: str) -> None:
    """Both forms an integration merge can produce must pass unlinted."""
    result = _lint(subject)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.requires_node_modules
@pytest.mark.parametrize(
    "subject",
    [
        "Merge pull request #12 from owner/topic",
        "Merge branch 'main'",
        "a subject carrying no conventional type",
    ],
)
def test_non_ignored_subjects_are_still_linted(subject: str) -> None:
    """The ignore must not widen past the two integration merge forms."""
    result = _lint(subject)
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.requires_node_modules
def test_conventional_subject_is_accepted() -> None:
    result = _lint("fix(ci): a real conventional subject")
    assert result.returncode == 0, result.stdout + result.stderr

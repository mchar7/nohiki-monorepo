from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from _documents import load_mapping, load_workflow, string_at

_ROOT = Path(__file__).resolve().parents[3]
_TYPESCRIPT = _ROOT / "typescript"
_LEFTHOOK = _ROOT / "lefthook.yml"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_COMMIT_MESSAGE_CORPUS = (
    ("fix(k8s): accept an established alphanumeric scope", True),
    ("fix(s3-client): accept a hyphenated alphanumeric scope", True),
    ("docs: accept a message without a scope", True),
    ("fix(K8s): reject upper-case scope characters", False),
    ("fix(k8s_api): reject underscore separators", False),
    ("fix(): reject explicit empty parentheses", False),
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


def _named_run(node: object, name: str) -> str:
    if isinstance(node, Mapping):
        if node.get("name") == name:
            run = node.get("run")
            assert isinstance(run, str)
            return run
        for child in node.values():
            try:
                return _named_run(child, name)
            except LookupError:
                pass
    elif isinstance(node, list):
        for child in node:
            try:
                return _named_run(child, name)
            except LookupError:
                pass
    raise LookupError(name)


def _edit_command(message_path: Path) -> list[str]:
    command = string_at(load_mapping(_LEFTHOOK), "commit-msg", "commands", "commitlint", "run")
    return shlex.split(command.replace("{1}", str(message_path)))


def _range_command(commit: str) -> list[str]:
    command = _named_run(load_workflow(_CHECKS)["jobs"]["worker"], "Validate PR commit messages")
    command = command.replace("${{ github.event.pull_request.base.sha }}", "HEAD")
    command = command.replace("${{ github.event.pull_request.head.sha }}", commit)
    return shlex.split(command)


def _lint_edit(subject: str, message_path: Path) -> subprocess.CompletedProcess[str]:
    message_path.write_text(f"{subject}\n", encoding="utf-8")
    return subprocess.run(
        _edit_command(message_path),
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
        _range_command(commit),
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.requires_node_modules
def test_local_edit_and_hosted_range_paths_agree_on_one_corpus(tmp_path: Path) -> None:
    def evaluate(index: int) -> tuple[str, bool, subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
        subject, expected = _COMMIT_MESSAGE_CORPUS[index]
        return subject, expected, _lint_edit(subject, tmp_path / f"message-{index}"), _lint_range(subject)

    workers = min(len(_COMMIT_MESSAGE_CORPUS), os.process_cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(evaluate, range(len(_COMMIT_MESSAGE_CORPUS))))

    for subject, expected, local, hosted in outcomes:
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

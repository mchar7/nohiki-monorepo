from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_TYPESCRIPT = _ROOT / "typescript"


def _lint(subject: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pnpm", "exec", "commitlint"],
        input=subject,
        cwd=_TYPESCRIPT,
        capture_output=True,
        text=True,
        check=False,
    )


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

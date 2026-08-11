"""Behavioral checks for the owner-controlled local secrets mirror."""

from __future__ import annotations

import os
import stat
import subprocess
import time
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "dev" / "secrets-mirror.sh"
_REQUIRED_DIRECTORIES = (
    "database",
    "email",
    "gcp",
    "jsearch",
    "jwt",
    "kafka",
    "llm",
    "oauth",
    "qdrant",
    "redis",
    "s3",
    "s3-job-correlation",
    "s3-ml-compute",
    "s3-mlflow",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    secrets = repo / "infra" / "shared" / "secrets"
    secrets.mkdir(parents=True)
    for directory in _REQUIRED_DIRECTORIES:
        (secrets / directory).mkdir()
    (secrets / "README.md").write_text("tracked documentation\n", encoding="utf-8")
    source = secrets / "database" / "dsn"
    source.write_bytes(b"test fixture value")
    source.chmod(0o600)

    repo.mkdir(exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "add", "infra/shared/secrets/README.md")
    _git(repo, "commit", "-qm", "test fixture")
    return repo


def _run(repo: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    state = tmp_path / "state"
    environment = os.environ | {
        "HOME": str(tmp_path / "home"),
        "XDG_STATE_HOME": str(state),
    }
    return subprocess.run(
        [str(_SCRIPT)],
        cwd=repo,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_missing_mirror_is_warned_then_refreshed_without_leaking_names(tmp_path: Path) -> None:
    repo = _repository(tmp_path)

    result = _run(repo, tmp_path)

    mirror = tmp_path / "state" / "nohiki-secrets-mirror"
    mirrored_file = mirror / "database" / "dsn"
    assert result.returncode == 0
    assert result.stdout == "secrets mirror: refreshed 1 file(s)\n"
    assert "mirror is missing" in result.stderr
    assert "database" not in result.stdout + result.stderr
    assert "dsn" not in result.stdout + result.stderr
    assert mirrored_file.read_bytes() == b"test fixture value"
    assert stat.S_IMODE(mirrored_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(mirror.stat().st_mode) == 0o700
    assert not (mirror / "README.md").exists()
    assert (mirror / ".last-refresh").is_file()


def test_stale_mirror_warns_and_refreshes(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    assert _run(repo, tmp_path).returncode == 0
    marker = tmp_path / "state" / "nohiki-secrets-mirror" / ".last-refresh"
    stale = time.time() - (9 * 24 * 60 * 60)
    os.utime(marker, (stale, stale))

    result = _run(repo, tmp_path)

    assert result.returncode == 0
    assert "more than 7 days stale" in result.stderr
    assert marker.stat().st_mtime > stale


def test_sparse_checkout_fails_before_touching_the_mirror(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    assert _run(repo, tmp_path).returncode == 0
    mirror_file = tmp_path / "state" / "nohiki-secrets-mirror" / "database" / "dsn"
    before = mirror_file.stat().st_mtime_ns
    _git(repo, "config", "core.sparseCheckout", "true")

    result = _run(repo, tmp_path)

    assert result.returncode != 0
    assert "sparse checkout is prohibited" in result.stderr
    assert mirror_file.stat().st_mtime_ns == before


def test_linked_worktree_refreshes_from_the_primary_worktree(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked), "HEAD")
    assert not (linked / "infra" / "shared" / "secrets" / "database").exists()

    result = _run(linked, tmp_path)

    mirror_file = tmp_path / "state" / "nohiki-secrets-mirror" / "database" / "dsn"
    assert result.returncode == 0
    assert result.stdout == "secrets mirror: refreshed 1 file(s)\n"
    assert mirror_file.is_file()

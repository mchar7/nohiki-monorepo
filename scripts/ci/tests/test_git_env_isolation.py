"""Regression: hook-exported Git env must not leak into scratch-repo git calls.

Git exports ``GIT_DIR`` (and siblings) to hooks. When a suite runs inside a pre-push hook
from a linked worktree, a fixture that shells out to ``git init`` obeys the leaked worktree
``GIT_DIR`` and operates on the real repository instead of its scratch tree. The damage is
not limited to configuration: the init re-initializes the shared repository as bare
(``core.bare = true``), and the ``git add``/``git commit``/``git checkout`` calls that follow
it rewrite tracked files, delete them, and move the checked-out branch to a commit whose tree
holds only the fixture's scratch files.

``nohiki_test_utils.plugins._scrub_git_discovery_env`` removes those vars. It lives in the
shared pytest11 plugin rather than a conftest so that packages without one are still covered,
and it is SESSION-scoped so it runs before module-scoped fixtures (e.g. the cluster-reset
harness) that call git.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _clean_env() -> dict[str, str]:
    from nohiki_test_utils import plugins

    return {key: value for key, value in os.environ.items() if key not in plugins._GIT_DISCOVERY_ENV}


def _core_bare(config: Path) -> str:
    result = subprocess.run(
        ["git", "config", "--file", str(config), "--get", "core.bare"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "false"


def _outer_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build an outer repo with a linked worktree; return (shared_config, wt_gitdir, scratch)."""
    outer = tmp_path / "outer"
    outer.mkdir()
    env = _clean_env()
    subprocess.run(["git", "init", "-q"], cwd=outer, env=env, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "init"],
        cwd=outer,
        env=env,
        check=True,
    )
    subprocess.run(["git", "worktree", "add", "-q", str(tmp_path / "wt")], cwd=outer, env=env, check=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return outer / ".git" / "config", outer / ".git" / "worktrees" / "wt", scratch


def test_scrub_git_discovery_env_is_session_scoped() -> None:
    """The scrub must be session-scoped and cover GIT_DIR.

    A function-scoped scrub runs after module-scoped fixtures that call git, defeating the
    isolation the fixture exists to provide.
    """
    from nohiki_test_utils import plugins

    marker = plugins._scrub_git_discovery_env._fixture_function_marker
    assert marker.scope == "session", f"expected session scope, got {marker.scope!r}"
    assert marker.autouse, "the scrub must be autouse: no package opts in explicitly"
    assert "GIT_DIR" in plugins._GIT_DISCOVERY_ENV


def test_leaked_worktree_git_dir_corrupts_shared_config(tmp_path: Path) -> None:
    """Document the hazard.

    A scratch ``git init`` under a leaked worktree GIT_DIR re-inits the shared repo as bare.
    """
    shared_config, wt_gitdir, scratch = _outer_worktree(tmp_path)
    assert _core_bare(shared_config) == "false"
    subprocess.run(["git", "init", "-q"], cwd=scratch, env=_clean_env() | {"GIT_DIR": str(wt_gitdir)}, check=False)
    assert _core_bare(shared_config) == "true"


def test_scrubbed_env_isolates_scratch_git_init(tmp_path: Path) -> None:
    """Isolate the scratch init.

    Scrubbing ``_GIT_DISCOVERY_ENV`` makes the scratch ``git init`` target the scratch repo
    and leave the shared config untouched.
    """
    from nohiki_test_utils import plugins

    shared_config, wt_gitdir, scratch = _outer_worktree(tmp_path)
    leaked = _clean_env() | {"GIT_DIR": str(wt_gitdir)}
    scrubbed = {key: value for key, value in leaked.items() if key not in plugins._GIT_DISCOVERY_ENV}
    subprocess.run(["git", "init", "-q"], cwd=scratch, env=scrubbed, check=True)
    assert (scratch / ".git").exists()
    assert _core_bare(shared_config) == "false"


_CONFTEST_LESS_TEST = """
import os
import subprocess


def test_scratch_git_init_stays_in_the_scratch_repo(tmp_path):
    assert "GIT_DIR" not in os.environ
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=scratch, check=True)
    assert (scratch / ".git").exists()
"""


def test_shared_plugin_protects_a_package_with_no_conftest(tmp_path: Path) -> None:
    """A package that declares no conftest must still be isolated.

    This is the property that makes the guard's home correct. The scrub used to live in one
    package's conftest, so every other package that shelled out to git ran unprotected, and
    each newly collected package regressed the hazard silently. The inner session runs with a
    leaked worktree ``GIT_DIR`` and no conftest anywhere above it, so only the shared plugin
    can clear the variable.
    """
    shared_config, wt_gitdir, _ = _outer_worktree(tmp_path)
    package = tmp_path / "conftest_less_package"
    package.mkdir()
    (package / "test_scratch_init.py").write_text(_CONFTEST_LESS_TEST, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_scratch_init.py"],
        cwd=package,
        env=_clean_env() | {"GIT_DIR": str(wt_gitdir)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"inner session failed:\n{result.stdout}\n{result.stderr}"
    assert _core_bare(shared_config) == "false"

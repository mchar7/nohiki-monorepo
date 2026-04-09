"""Tests for nohiki_test_utils.paths module."""

from __future__ import annotations

from pathlib import Path

import pytest
from nohiki_test_utils.paths import get_repo_root, get_test_secrets_dir


class TestGetRepoRoot:
    """Tests for get_repo_root path resolution."""

    def setup_method(self) -> None:
        """Clear the LRU cache before each test to ensure isolation."""
        get_repo_root.cache_clear()

    def teardown_method(self) -> None:
        """Clear the LRU cache after each test."""
        get_repo_root.cache_clear()

    def test_returns_path(self) -> None:
        """get_repo_root returns a Path object."""
        root = get_repo_root()
        assert isinstance(root, Path)

    def test_root_contains_workspace_pyproject(self) -> None:
        """Resolved root contains a pyproject.toml with [tool.uv.workspace]."""
        root = get_repo_root()
        pyproject = root / "pyproject.toml"
        assert pyproject.is_file()
        assert "[tool.uv.workspace]" in pyproject.read_text()

    def test_returns_absolute_path(self) -> None:
        """get_repo_root returns an absolute path."""
        root = get_repo_root()
        assert root.is_absolute()

    def test_project_root_env_var_takes_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """PROJECT_ROOT env var is used when set."""
        monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
        get_repo_root.cache_clear()
        root = get_repo_root()
        assert root == tmp_path

    def test_walk_up_fallback_without_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Walk-up discovery works when PROJECT_ROOT is not set."""
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        get_repo_root.cache_clear()
        root = get_repo_root()
        assert isinstance(root, Path)
        assert (root / "pyproject.toml").is_file()

    def test_raises_when_no_workspace_marker_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """FileNotFoundError raised when walk-up traversal finds no workspace pyproject.toml."""
        fake_file = tmp_path / "subdir" / "paths.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        monkeypatch.setattr("nohiki_test_utils.paths.__file__", str(fake_file))
        get_repo_root.cache_clear()
        with pytest.raises(FileNotFoundError, match="Could not find monorepo root"):
            get_repo_root()

    def test_result_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Repeated calls return the same cached object."""
        monkeypatch.delenv("PROJECT_ROOT", raising=False)
        get_repo_root.cache_clear()
        root1 = get_repo_root()
        root2 = get_repo_root()
        assert root1 is root2


class TestGetTestSecretsDir:
    """Tests for get_test_secrets_dir path construction."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        get_repo_root.cache_clear()

    def teardown_method(self) -> None:
        """Clear cache after each test."""
        get_repo_root.cache_clear()

    def test_returns_path_under_repo_root(self) -> None:
        """Secrets dir is under the resolved repo root."""
        root = get_repo_root()
        secrets_dir = get_test_secrets_dir()
        assert isinstance(secrets_dir, Path)
        assert secrets_dir.is_relative_to(root)

    def test_path_structure(self) -> None:
        """Secrets dir has the expected infra/shared/secrets structure."""
        secrets_dir = get_test_secrets_dir()
        assert secrets_dir.parts[-3:] == ("infra", "shared", "secrets")

    def test_secrets_dir_exists(self) -> None:
        """Secrets dir points to an existing directory in the repository."""
        secrets_dir = get_test_secrets_dir()
        assert secrets_dir.is_dir(), f"Secrets directory not found at {secrets_dir}"

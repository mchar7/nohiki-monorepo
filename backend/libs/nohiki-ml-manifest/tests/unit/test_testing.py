"""Tests for nohiki_ml_manifest.testing utilities."""

from pathlib import Path

from nohiki_ml_manifest.cache import DEFAULT_MANIFEST_PATH
from nohiki_ml_manifest.testing import get_test_manifest_path


class TestGetTestManifestPath:
    """Tests for get_test_manifest_path utility."""

    def test_returns_path_instance(self) -> None:
        """Test that get_test_manifest_path returns a Path."""
        result = get_test_manifest_path()
        assert isinstance(result, Path)

    def test_ends_with_default_manifest_path(self) -> None:
        """Test returned path ends with the canonical DEFAULT_MANIFEST_PATH."""
        result = get_test_manifest_path()
        assert result.parts[-len(DEFAULT_MANIFEST_PATH.parts) :] == DEFAULT_MANIFEST_PATH.parts

    def test_file_exists(self) -> None:
        """Test that the resolved manifest path points to an existing file."""
        result = get_test_manifest_path()
        assert result.exists(), f"Manifest file not found at {result}"

    def test_is_absolute(self) -> None:
        """Test that the returned path is absolute."""
        result = get_test_manifest_path()
        assert result.is_absolute()

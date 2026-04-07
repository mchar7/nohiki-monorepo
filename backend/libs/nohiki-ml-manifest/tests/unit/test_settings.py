"""Tests for ManifestMixin settings validation."""

import json
from pathlib import Path

import pytest
from nohiki_ml_manifest.cache import DEFAULT_MANIFEST_PATH
from nohiki_ml_manifest.settings import ManifestMixin
from pydantic_settings import BaseSettings


class ConcreteSettings(ManifestMixin, BaseSettings):
    """Concrete settings class for testing ManifestMixin."""

    model_config = {"extra": "ignore"}
    environment: str = "test"


class TestManifestMixin:
    """Tests for ManifestMixin path validation."""

    def test_valid_manifest_path(self, tmp_path: Path, sample_manifest_data: dict) -> None:
        """Test that a valid manifest path passes validation."""
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(sample_manifest_data))

        settings = ConcreteSettings(manifest_path=manifest_file)

        assert settings.manifest_path == manifest_file

    def test_missing_manifest_path_raises(self, tmp_path: Path) -> None:
        """Test that a non-existent manifest path raises ValueError."""
        with pytest.raises(ValueError, match="Manifest file not found"):
            ConcreteSettings(manifest_path=tmp_path / "nonexistent.json")

    def test_default_manifest_path_value(self) -> None:
        """Test that default manifest path is the expected constant."""
        assert ConcreteSettings.model_fields["manifest_path"].default == DEFAULT_MANIFEST_PATH

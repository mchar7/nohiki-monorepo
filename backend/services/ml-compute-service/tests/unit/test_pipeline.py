"""Unit tests for pipeline module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetEncodingPipeline:
    """Tests for get_encoding_pipeline function."""

    def test_creates_pipeline_with_manifest(self) -> None:
        """Verifies pipeline is created with manifest from get_manifest()."""
        mock_manifest = MagicMock()
        mock_manifest.collections.jobs.version = "jobs-v1"
        mock_manifest.collections.profiles.version = "profiles-v1"
        mock_manifest.collections.skills.version = "skills-v1"
        mock_manifest.late_interaction.model_id = "colbert-test"
        mock_pipeline = MagicMock()

        manifest_patch = patch(
            "ml_compute_service.core.pipeline.get_manifest",
            return_value=mock_manifest,
        )
        pipeline_patch = patch(
            "ml_compute_service.core.pipeline.MLEncodingPipeline",
            return_value=mock_pipeline,
        )

        with manifest_patch, pipeline_patch as mock_pipeline_cls:
            from ml_compute_service.core.pipeline import get_encoding_pipeline

            get_encoding_pipeline.cache_clear()
            result = get_encoding_pipeline()

            mock_pipeline_cls.assert_called_once_with(manifest=mock_manifest)
            assert result == mock_pipeline

            get_encoding_pipeline.cache_clear()


class TestResetPipeline:
    """Tests for reset_pipeline function."""

    def test_clears_pipeline_cache(self) -> None:
        """Verifies reset_pipeline clears the cached pipeline."""
        with patch("ml_compute_service.core.pipeline.get_encoding_pipeline") as mock_get_pipeline:
            from ml_compute_service.core.pipeline import reset_pipeline

            reset_pipeline()

            mock_get_pipeline.cache_clear.assert_called_once()

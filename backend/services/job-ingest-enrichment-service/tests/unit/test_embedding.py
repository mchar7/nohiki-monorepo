"""Unit tests for embedding client configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from job_ingest_enrichment_service.core.config import get_manifest
from job_ingest_enrichment_service.core.embedding import get_embedding_publisher


class TestGetManifest:
    """Tests for get_manifest delegates to ManifestCache."""

    def test_delegates_to_manifest_cache(self) -> None:
        """get_manifest delegates to ManifestCache.get with settings path."""
        with patch("job_ingest_enrichment_service.core.config.ManifestCache") as mock_cache:
            mock_cache.get.return_value = MagicMock()
            result = get_manifest()

        assert result is mock_cache.get.return_value
        mock_cache.get.assert_called_once()


def _clear_publisher_cache() -> None:
    get_embedding_publisher.cache_clear()


class TestGetEmbeddingPublisher:
    """Tests for get_embedding_publisher singleton."""

    def setup_method(self) -> None:
        _clear_publisher_cache()

    def teardown_method(self) -> None:
        _clear_publisher_cache()

    def test_creates_publisher_with_manifest_version(self) -> None:
        """Creates EmbeddingPublisher with collection version from manifest."""
        mock_manifest = MagicMock()
        mock_manifest.get_entity_version.return_value = "v3"
        mock_settings = MagicMock()
        mock_settings.service_name = "job-ingest-enrichment-service"

        with (
            patch("job_ingest_enrichment_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("job_ingest_enrichment_service.core.embedding.get_settings", return_value=mock_settings),
            patch("job_ingest_enrichment_service.core.embedding.EmbeddingPublisher") as mock_cls,
        ):
            result = get_embedding_publisher()

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args
        assert call_kwargs.kwargs["service_name"] == "job-ingest-enrichment-service"
        assert call_kwargs.kwargs["collection_version"] == "v3"
        assert result is mock_cls.return_value

    def test_returns_same_instance_on_repeated_calls(self) -> None:
        """Returns cached instance without re-initializing."""
        mock_manifest = MagicMock()
        mock_manifest.get_entity_version.return_value = "v1"
        mock_settings = MagicMock()
        mock_settings.service_name = "job-ingest-enrichment-service"

        with (
            patch("job_ingest_enrichment_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("job_ingest_enrichment_service.core.embedding.get_settings", return_value=mock_settings),
            patch("job_ingest_enrichment_service.core.embedding.EmbeddingPublisher") as mock_cls,
        ):
            first = get_embedding_publisher()
            second = get_embedding_publisher()

        assert first is second
        mock_cls.assert_called_once()

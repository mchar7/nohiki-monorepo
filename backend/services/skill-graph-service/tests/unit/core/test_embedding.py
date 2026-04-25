"""Tests for embedding publisher factory functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nohiki_embedding_client import EmbeddingPublisher
from nohiki_kafka_client import Topics
from skill_graph_service.core.embedding import (
    get_batch_embedding_publisher,
    get_normalization_embedding_publisher,
    get_skill_embedding_publisher,
)


def _clear_all_caches() -> None:
    get_batch_embedding_publisher.cache_clear()
    get_normalization_embedding_publisher.cache_clear()
    get_skill_embedding_publisher.cache_clear()


def _make_mocks() -> tuple[MagicMock, MagicMock]:
    mock_manifest = MagicMock()
    mock_manifest.get_entity_version.return_value = "v1"
    mock_settings = MagicMock()
    mock_settings.service_name = "skill-graph-service"
    return mock_manifest, mock_settings


class TestGetBatchEmbeddingPublisher:
    """Tests for get_batch_embedding_publisher singleton."""

    def setup_method(self) -> None:
        _clear_all_caches()

    def teardown_method(self) -> None:
        _clear_all_caches()

    def test_returns_embedding_publisher(self) -> None:
        """Returns an EmbeddingPublisher instance."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_batch_embedding_publisher()
        assert isinstance(publisher, EmbeddingPublisher)

    def test_callback_topic(self) -> None:
        """Uses SKILL_BATCH_EMBEDDING_CALLBACK as the callback topic."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_batch_embedding_publisher()
        assert publisher.callback_topic == Topics.SKILL_BATCH_EMBEDDING_CALLBACK

    def test_service_name(self) -> None:
        """Carries the configured service name."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_batch_embedding_publisher()
        assert publisher.service_name == "skill-graph-service"

    def test_collection_version(self) -> None:
        """Uses the version from the manifest."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_batch_embedding_publisher()
        assert publisher.collection_version == "v1"

    def test_fire_and_forget_api(self) -> None:
        """Exposes request_batch_embedding without a timeout parameter."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_batch_embedding_publisher()
        assert callable(publisher.request_batch_embedding)
        assert not hasattr(publisher, "timeout_seconds")

    def test_singleton(self) -> None:
        """Repeated calls return the same cached instance."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            p1 = get_batch_embedding_publisher()
            p2 = get_batch_embedding_publisher()
        assert p1 is p2


class TestGetNormalizationEmbeddingPublisher:
    """Tests for get_normalization_embedding_publisher singleton."""

    def setup_method(self) -> None:
        _clear_all_caches()

    def teardown_method(self) -> None:
        _clear_all_caches()

    def test_returns_embedding_publisher(self) -> None:
        """Returns an EmbeddingPublisher instance."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_normalization_embedding_publisher()
        assert isinstance(publisher, EmbeddingPublisher)

    def test_callback_topic_is_normalization_specific(self) -> None:
        """Uses a separate normalization-specific callback topic, distinct from the batch topic."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_normalization_embedding_publisher()
        assert publisher.callback_topic == Topics.SKILL_NORMALIZATION_EMBEDDING_CALLBACK
        assert publisher.callback_topic != Topics.SKILL_BATCH_EMBEDDING_CALLBACK

    def test_singleton(self) -> None:
        """Repeated calls return the same cached instance."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            p1 = get_normalization_embedding_publisher()
            p2 = get_normalization_embedding_publisher()
        assert p1 is p2


class TestGetSkillEmbeddingPublisher:
    """Tests for get_skill_embedding_publisher singleton."""

    def setup_method(self) -> None:
        _clear_all_caches()

    def teardown_method(self) -> None:
        _clear_all_caches()

    def test_returns_embedding_publisher(self) -> None:
        """Returns an EmbeddingPublisher instance."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_skill_embedding_publisher()
        assert isinstance(publisher, EmbeddingPublisher)

    def test_callback_topic(self) -> None:
        """Uses SKILL_EMBEDDING_CALLBACK as the callback topic."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_skill_embedding_publisher()
        assert publisher.callback_topic == Topics.SKILL_EMBEDDING_CALLBACK

    def test_exposes_request_embedding(self) -> None:
        """Exposes request_embedding for single-skill vectorisation."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            publisher = get_skill_embedding_publisher()
        assert callable(publisher.request_embedding)

    def test_singleton(self) -> None:
        """Repeated calls return the same cached instance."""
        mock_manifest, mock_settings = _make_mocks()
        with (
            patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
            patch("skill_graph_service.core.embedding.get_settings", return_value=mock_settings),
        ):
            p1 = get_skill_embedding_publisher()
            p2 = get_skill_embedding_publisher()
        assert p1 is p2

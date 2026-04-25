"""Unit tests for the embedding_client re-export module."""

from __future__ import annotations

from nohiki_embedding_client import EmbeddingPublisher
from nohiki_kafka_client import Topics
from skill_graph_service.services.embedding_client import get_skill_embedding_publisher


class TestGetSkillEmbeddingPublisherReexport:
    """Tests that embedding_client correctly re-exports get_skill_embedding_publisher."""

    def test_returns_embedding_publisher_instance(self) -> None:
        """Re-exported function returns an EmbeddingPublisher."""
        publisher = get_skill_embedding_publisher()
        assert isinstance(publisher, EmbeddingPublisher)

    def test_callback_topic_is_skill_embedding_callback(self) -> None:
        """Publisher is configured for the skill embedding callback topic."""
        publisher = get_skill_embedding_publisher()
        assert publisher.callback_topic == Topics.SKILL_EMBEDDING_CALLBACK

    def test_singleton_returns_same_instance(self) -> None:
        """Repeated calls return the same cached publisher instance."""
        assert get_skill_embedding_publisher() is get_skill_embedding_publisher()

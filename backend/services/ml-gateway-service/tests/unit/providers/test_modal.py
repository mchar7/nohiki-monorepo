"""Tests for ModalMLProvider."""

from __future__ import annotations

from ml_gateway_service.providers.base import MLOperationType, ProviderCapabilities
from ml_gateway_service.providers.modal import ModalMLProvider
from nohiki_kafka_client import Topics


class TestModalMLProvider:
    """Tests for ModalMLProvider."""

    def test_name(self, modal_provider: ModalMLProvider) -> None:
        """Test provider name is 'modal'."""
        assert modal_provider.name == "modal"

    def test_capabilities(self, modal_provider: ModalMLProvider) -> None:
        """Test Modal provider capabilities."""
        caps = modal_provider.capabilities
        assert isinstance(caps, ProviderCapabilities)
        assert caps.supports_embedding is True
        assert caps.supports_rerank is True
        assert caps.max_batch_size == 64
        assert caps.gpu_available is True

    def test_get_target_topic_embedding(
        self,
        modal_provider: ModalMLProvider,
    ) -> None:
        """Test get_target_topic for embedding operation."""
        topic = modal_provider.get_target_topic(MLOperationType.EMBEDDING)
        assert topic == Topics.ML_INTERNAL_MODAL_COMPUTE

    def test_get_target_topic_rerank(
        self,
        modal_provider: ModalMLProvider,
    ) -> None:
        """Test get_target_topic for rerank operation."""
        topic = modal_provider.get_target_topic(MLOperationType.RERANK)
        assert topic == Topics.ML_INTERNAL_MODAL_COMPUTE

    def test_default_enabled(self, modal_provider: ModalMLProvider) -> None:
        """Test Modal is enabled by default."""
        assert modal_provider.default_enabled() is True

    def test_default_priority(self, modal_provider: ModalMLProvider) -> None:
        """Test Modal has lower priority than K8s (50)."""
        assert modal_provider.default_priority() == 50

    def test_health_check(self, modal_provider: ModalMLProvider) -> None:
        """Test health check returns True."""
        assert modal_provider.health_check() is True

    def test_supports_embedding(self, modal_provider: ModalMLProvider) -> None:
        """Test provider supports embedding."""
        assert modal_provider.supports_operation(MLOperationType.EMBEDDING) is True

    def test_supports_rerank(self, modal_provider: ModalMLProvider) -> None:
        """Test provider supports rerank (has GPU)."""
        assert modal_provider.supports_operation(MLOperationType.RERANK) is True

    def test_repr(self, modal_provider: ModalMLProvider) -> None:
        """Test string representation."""
        repr_str = repr(modal_provider)
        assert "ModalMLProvider" in repr_str
        assert "modal" in repr_str

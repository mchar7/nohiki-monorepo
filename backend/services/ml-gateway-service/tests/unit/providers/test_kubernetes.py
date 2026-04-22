"""Tests for KubernetesMLProvider."""

from __future__ import annotations

from ml_gateway_service.providers.base import MLOperationType, ProviderCapabilities
from ml_gateway_service.providers.kubernetes import KubernetesMLProvider
from nohiki_kafka_client import Topics


class TestKubernetesMLProvider:
    """Tests for KubernetesMLProvider."""

    def test_name(self, kubernetes_provider: KubernetesMLProvider) -> None:
        """Test provider name is 'kubernetes'."""
        assert kubernetes_provider.name == "kubernetes"

    def test_capabilities(self, kubernetes_provider: KubernetesMLProvider) -> None:
        """Test Kubernetes provider capabilities."""
        caps = kubernetes_provider.capabilities
        assert isinstance(caps, ProviderCapabilities)
        assert caps.supports_embedding is True
        assert caps.supports_rerank is False
        assert caps.max_batch_size == 100
        assert caps.gpu_available is False

    def test_get_target_topic_embedding(
        self,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test get_target_topic for embedding operation."""
        topic = kubernetes_provider.get_target_topic(MLOperationType.EMBEDDING)
        assert topic == Topics.ML_INTERNAL_K8S_COMPUTE

    def test_get_target_topic_rerank(
        self,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test get_target_topic for rerank operation."""
        topic = kubernetes_provider.get_target_topic(MLOperationType.RERANK)
        assert topic == Topics.ML_INTERNAL_K8S_COMPUTE

    def test_default_enabled(self, kubernetes_provider: KubernetesMLProvider) -> None:
        """Test Kubernetes is enabled by default."""
        assert kubernetes_provider.default_enabled() is True

    def test_default_priority(self, kubernetes_provider: KubernetesMLProvider) -> None:
        """Test Kubernetes has high priority (10)."""
        assert kubernetes_provider.default_priority() == 10

    def test_health_check(
        self,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test health check returns True."""
        assert kubernetes_provider.health_check() is True

    def test_supports_embedding(
        self,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test provider supports embedding."""
        assert kubernetes_provider.supports_operation(MLOperationType.EMBEDDING) is True

    def test_does_not_support_rerank(
        self,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test provider does not support rerank (no GPU)."""
        assert kubernetes_provider.supports_operation(MLOperationType.RERANK) is False

    def test_repr(self, kubernetes_provider: KubernetesMLProvider) -> None:
        """Test string representation."""
        repr_str = repr(kubernetes_provider)
        assert "KubernetesMLProvider" in repr_str
        assert "kubernetes" in repr_str

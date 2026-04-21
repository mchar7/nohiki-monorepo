"""Kubernetes ML provider implementation.

Routes ML work to in-cluster Kubernetes workers (ml-compute-service deployment).
Workers consume from ml.internal.k8s-compute.v1 and use nohiki-ml-core for inference.
"""

from __future__ import annotations

from nohiki_kafka_client import Topics

from ml_gateway_service.providers.base import (
    BaseMLProvider,
    MLOperationType,
    ProviderCapabilities,
)

# BatchEmbeddingRequested item-count contract for the Kubernetes worker.
_KUBERNETES_MAX_BATCH_ITEMS = 100


class KubernetesMLProvider(BaseMLProvider):
    """Routes ML work to in-cluster Kubernetes workers.

    Workers are deployed as a separate Deployment (ml-compute-service)
    that consumes from the internal K8s topic and uses nohiki-ml-core
    for actual ML inference.

    Capabilities:
        - Embedding: Yes (CPU-optimized ColBERT + MUVERA)
        - Rerank: No (requires GPU for Qwen3-Reranker)

    Target Topic: ml.internal.k8s-compute.v1
    """

    @property
    def name(self) -> str:
        """Return provider name."""
        return "kubernetes"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return Kubernetes worker capabilities."""
        return ProviderCapabilities(
            supports_embedding=True,
            supports_rerank=False,
            max_batch_size=_KUBERNETES_MAX_BATCH_ITEMS,
            gpu_available=False,
        )

    def get_target_topic(self, operation: MLOperationType) -> str:
        """Return Kafka topic for Kubernetes worker."""
        del operation  # All operations use the same topic
        return Topics.ML_INTERNAL_K8S_COMPUTE

    def default_enabled(self) -> bool:
        """Return True - Kubernetes is the default provider."""
        return True

    def default_priority(self) -> int:
        """Return priority 10 - high priority for cost-effective embeddings."""
        return 10

    def health_check(self) -> bool:
        """Check if Kubernetes workers are healthy."""
        return True

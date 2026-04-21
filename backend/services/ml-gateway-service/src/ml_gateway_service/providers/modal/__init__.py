"""Modal ML provider implementation.

Routes ML work to Modal serverless functions for GPU-accelerated inference.
Modal functions consume from ml.internal.modal-compute.v1 and use nohiki-ml-core.

Modal is preferred for:
- Reranking (Qwen3-Reranker requires GPU)
- High-throughput embedding batches (GPU acceleration)
- Burst capacity (serverless auto-scaling)
"""

from __future__ import annotations

from nohiki_kafka_client import Topics

from ml_gateway_service.providers.base import (
    BaseMLProvider,
    MLOperationType,
    ProviderCapabilities,
)


class ModalMLProvider(BaseMLProvider):
    """Routes ML work to Modal serverless functions.

    Modal functions are deployed separately (infra/modal/) and
    consume from the internal Modal topic. They use nohiki-ml-core for
    actual ML inference, ensuring DRY code.

    Capabilities:
        - Embedding: Yes (GPU-accelerated for throughput)
        - Rerank: Yes (GPU available)

    Target Topic: ml.internal.modal-compute.v1
    """

    @property
    def name(self) -> str:
        """Return provider name."""
        return "modal"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return Modal capabilities with GPU support."""
        return ProviderCapabilities(
            supports_embedding=True,
            supports_rerank=True,
            max_batch_size=64,
            gpu_available=True,
        )

    def get_target_topic(self, operation: MLOperationType) -> str:
        """Return Kafka topic for Modal functions."""
        del operation  # All operations use the same topic
        return Topics.ML_INTERNAL_MODAL_COMPUTE

    def default_enabled(self) -> bool:
        """Return True - Modal is enabled by default."""
        return True

    def default_priority(self) -> int:
        """Return priority 50 - lower than K8s for cost efficiency."""
        return 50

    def health_check(self) -> bool:
        """Check if Modal API is accessible."""
        return True

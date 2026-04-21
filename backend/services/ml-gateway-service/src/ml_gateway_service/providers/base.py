"""Abstract base class for ML routing providers.

Architecture: ml-gateway-service is ROUTING ONLY. Providers return target Kafka
topics - they do NOT execute ML compute. Actual ML execution happens in:
- ml-compute-service (Kubernetes) - consumes ml.internal.k8s-compute.v1
- Modal functions - consumes ml.internal.modal-compute.v1

This ensures:
1. EDA compliance: All inter-service ML work uses Kafka events
2. DRY: ML code lives in nohiki-ml-core, used by all compute workers
3. Clean boundaries: Gateway routes, workers execute
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from ml_gateway_service.core.config import ProviderFallbackSettings


class MLOperationType(StrEnum):
    """Types of ML operations that providers can handle."""

    EMBEDDING = "embedding"
    RERANK = "rerank"
    BATCH_EMBEDDING = "batch_embedding"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Declares what operations a provider can handle."""

    supports_embedding: bool = True
    supports_rerank: bool = False
    supports_batch_embedding: bool = True
    max_batch_size: int = 32
    gpu_available: bool = False


class BaseMLProvider(ABC):
    """Abstract base class for ML compute providers.

    CRITICAL: Providers handle ROUTING decisions only. They return the Kafka
    topic to publish the work request to. They do NOT execute ML compute.

    The actual ML compute happens in consumers of the internal topics:
    - ml-compute-service consumes ml.internal.k8s-compute.v1
    - Modal functions consume ml.internal.modal-compute.v1

    This design ensures:
    - EDA compliance (all ML work via Kafka)
    - DRY (nohiki-ml-core used by all workers)
    - Clean separation (gateway routes, workers execute)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g., 'kubernetes', 'modal')."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declares what operations this provider can handle."""

    @abstractmethod
    def get_target_topic(self, operation: MLOperationType) -> str:
        """Return the Kafka topic to route this operation to.

        This is the ONLY responsibility of a provider - routing.
        The actual ML compute happens in consumers of these topics.

        Args:
            operation: Type of ML operation to route.

        Returns:
            Kafka topic name for internal routing.

        """

    def supports_operation(self, operation: MLOperationType) -> bool:
        """Check if this provider supports the given operation."""
        caps = self.capabilities
        match operation:
            case MLOperationType.EMBEDDING:
                return caps.supports_embedding
            case MLOperationType.RERANK:
                return caps.supports_rerank
            case MLOperationType.BATCH_EMBEDDING:
                return caps.supports_batch_embedding
            case _:
                return False

    def default_enabled(self) -> bool:
        """Return default enabled status when no explicit config is provided."""
        return False

    def default_priority(self) -> int:
        """Return default priority when no explicit config is provided."""
        return 100  # Lower = higher priority

    def default_fallback_settings(self) -> ProviderFallbackSettings:
        """Return default fallback settings when no explicit config is provided."""
        return ProviderFallbackSettings(
            enabled=True,
            min_consecutive_errors=3,
            error_duration_threshold_seconds=300,
        )

    def health_check(self) -> bool:
        """Check if the provider's target infrastructure is healthy.

        For Kubernetes provider: Check if worker pods are ready.
        For Modal provider: Check Modal API connectivity.

        Returns:
            True if healthy, False otherwise.

        """
        return True

    def __repr__(self) -> str:
        """Return string representation of provider."""
        return f"{self.__class__.__name__}(name={self.name!r})"

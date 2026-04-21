"""Auto-discovery of ML provider implementations.

Providers are routing-only - they return Kafka topics, not execute ML compute.
Actual ML execution happens in ml-compute-service (K8s) or Modal functions.
"""

from __future__ import annotations

from nohiki_observability import get_logger

from ml_gateway_service.providers.base import BaseMLProvider
from ml_gateway_service.providers.kubernetes import KubernetesMLProvider
from ml_gateway_service.providers.modal import ModalMLProvider

logger = get_logger(__name__)


def discover_providers() -> list[BaseMLProvider]:
    """Discover and instantiate all available ML providers.

    Returns:
        List of provider instances ordered by discovery.

    """
    providers: list[BaseMLProvider] = [
        KubernetesMLProvider(),
        ModalMLProvider(),
    ]

    for provider in providers:
        logger.info("Discovered ML provider", provider=provider.name)

    return providers

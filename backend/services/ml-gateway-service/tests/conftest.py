"""Pytest configuration and fixtures for ml-gateway-service tests."""

from __future__ import annotations

import os

os.environ["ML_GATEWAY_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["ML_GATEWAY_DATABASE__SCHEMA_NAME"] = "ml_gateway_schema"
os.environ["ML_GATEWAY_KAFKA__DSN"] = "kafka://localhost:29092"

# Disable OpenTelemetry completely during tests BEFORE any imports
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_LOGS_EXPORTER"] = "none"
os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"
os.environ["TEST_MODE"] = "true"

# Required settings for pydantic-settings validation (with service env prefix)
os.environ.setdefault("ML_GATEWAY_REDIS__DSN", "redis://localhost:6379/0")
os.environ.setdefault("ML_GATEWAY_KAFKA__DSN", "kafka://localhost:29092")
os.environ.setdefault("ML_GATEWAY_KAFKA__CONSUMER_GROUP", "ml-gateway-service")
os.environ.setdefault("ENVIRONMENT", "development")

# Now import after env vars are set
from typing import TYPE_CHECKING

import pytest
from ml_gateway_service.providers.base import (
    BaseMLProvider,
    MLOperationType,
    ProviderCapabilities,
)
from ml_gateway_service.providers.kubernetes import KubernetesMLProvider
from ml_gateway_service.providers.modal import ModalMLProvider
from ml_gateway_service.providers.registry import MLProviderRegistry, _RegistryHolder

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Reset settings cache between tests."""
    from ml_gateway_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def kubernetes_provider() -> KubernetesMLProvider:
    """Create a Kubernetes provider instance."""
    return KubernetesMLProvider()


@pytest.fixture
def modal_provider() -> ModalMLProvider:
    """Create a Modal provider instance."""
    return ModalMLProvider()


@pytest.fixture
def empty_registry() -> MLProviderRegistry:
    """Create an empty provider registry."""
    return MLProviderRegistry()


@pytest.fixture
def populated_registry(
    kubernetes_provider: KubernetesMLProvider,
    modal_provider: ModalMLProvider,
) -> MLProviderRegistry:
    """Create a registry with both providers registered."""
    registry = MLProviderRegistry()
    registry.register(kubernetes_provider, priority=10, enabled=True)
    registry.register(modal_provider, priority=50, enabled=True)
    return registry


@pytest.fixture(autouse=True)
def reset_registry_singleton() -> Iterator[None]:
    """Reset the registry singleton before and after each test."""
    _RegistryHolder.reset()
    yield
    _RegistryHolder.reset()


class MockProvider(BaseMLProvider):
    """Mock provider for testing."""

    def __init__(
        self,
        name: str = "mock",
        capabilities: ProviderCapabilities | None = None,
        target_topic: str = "mock.topic",
    ) -> None:
        """Initialize mock provider."""
        self._name = name
        self._capabilities = capabilities or ProviderCapabilities()
        self._target_topic = target_topic

    @property
    def name(self) -> str:
        """Return mock provider name."""
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return mock capabilities."""
        return self._capabilities

    def get_target_topic(self, operation: MLOperationType) -> str:
        """Return mock target topic."""
        del operation
        return self._target_topic


@pytest.fixture
def mock_provider() -> MockProvider:
    """Create a mock provider."""
    return MockProvider()


@pytest.fixture
def mock_gpu_provider() -> MockProvider:
    """Create a mock provider with GPU support."""
    return MockProvider(
        name="mock-gpu",
        capabilities=ProviderCapabilities(
            supports_embedding=True,
            supports_rerank=True,
            gpu_available=True,
        ),
        target_topic="mock.gpu.topic",
    )

"""Tests for MLProviderRegistry."""

from __future__ import annotations

import pytest
from ml_gateway_service.providers.base import MLOperationType
from ml_gateway_service.providers.kubernetes import KubernetesMLProvider
from ml_gateway_service.providers.registry import MLProviderRegistry


class TestMLProviderRegistry:
    """Tests for MLProviderRegistry."""

    def test_empty_registry(self, empty_registry: MLProviderRegistry) -> None:
        """Test empty registry has no providers."""
        assert len(empty_registry) == 0
        assert empty_registry.get_all_providers() == []

    def test_register_provider(
        self,
        empty_registry: MLProviderRegistry,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test registering a provider."""
        empty_registry.register(kubernetes_provider, priority=10, enabled=True)
        assert len(empty_registry) == 1
        assert "kubernetes" in empty_registry

    def test_register_duplicate_provider_raises(
        self,
        empty_registry: MLProviderRegistry,
        kubernetes_provider: KubernetesMLProvider,
    ) -> None:
        """Test registering duplicate provider raises ValueError."""
        empty_registry.register(kubernetes_provider)
        with pytest.raises(ValueError, match="already registered"):
            empty_registry.register(kubernetes_provider)

    def test_get_provider_by_name(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting provider by name."""
        provider = populated_registry.get_provider("kubernetes")
        assert provider is not None
        assert provider.name == "kubernetes"

    def test_get_provider_nonexistent(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting nonexistent provider returns None."""
        provider = populated_registry.get_provider("nonexistent")
        assert provider is None

    def test_get_enabled_provider(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting enabled provider."""
        provider = populated_registry.get_enabled_provider("kubernetes")
        assert provider is not None
        assert provider.name == "kubernetes"

    def test_get_enabled_provider_when_disabled(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting disabled provider returns None."""
        populated_registry.set_enabled("kubernetes", enabled=False)
        provider = populated_registry.get_enabled_provider("kubernetes")
        assert provider is None

    def test_get_provider_for_operation_embedding(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting provider for embedding operation."""
        provider = populated_registry.get_provider_for_operation(MLOperationType.EMBEDDING)
        assert provider is not None
        assert provider.name == "kubernetes"  # Higher priority

    def test_get_provider_for_operation_rerank(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting provider for rerank operation."""
        provider = populated_registry.get_provider_for_operation(MLOperationType.RERANK)
        assert provider is not None
        assert provider.name == "modal"  # Only provider with GPU

    def test_get_provider_for_operation_with_gpu_requirement(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting provider with GPU requirement."""
        provider = populated_registry.get_provider_for_operation(
            MLOperationType.EMBEDDING,
            require_gpu=True,
        )
        assert provider is not None
        assert provider.name == "modal"  # Only GPU provider

    def test_get_provider_for_operation_no_match(
        self,
        empty_registry: MLProviderRegistry,
    ) -> None:
        """Test getting provider when none match returns None."""
        provider = empty_registry.get_provider_for_operation(MLOperationType.EMBEDDING)
        assert provider is None

    def test_get_all_providers_ordered_by_priority(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting all providers returns them ordered by priority."""
        providers = populated_registry.get_all_providers()
        assert len(providers) == 2
        assert providers[0].name == "kubernetes"  # Priority 10
        assert providers[1].name == "modal"  # Priority 50

    def test_get_all_providers_enabled_only(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting only enabled providers."""
        populated_registry.set_enabled("modal", enabled=False)
        providers = populated_registry.get_all_providers(enabled_only=True)
        assert len(providers) == 1
        assert providers[0].name == "kubernetes"

    def test_get_all_providers_including_disabled(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting all providers including disabled."""
        populated_registry.set_enabled("modal", enabled=False)
        providers = populated_registry.get_all_providers(enabled_only=False)
        assert len(providers) == 2

    def test_get_primary_provider(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting primary provider returns highest priority."""
        provider = populated_registry.get_primary_provider()
        assert provider is not None
        assert provider.name == "kubernetes"

    def test_get_primary_provider_empty_registry(
        self,
        empty_registry: MLProviderRegistry,
    ) -> None:
        """Test getting primary provider from empty registry returns None."""
        provider = empty_registry.get_primary_provider()
        assert provider is None

    def test_get_fallback_providers(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test getting fallback providers."""
        fallbacks = populated_registry.get_fallback_providers(
            MLOperationType.EMBEDDING,
            exclude="kubernetes",
        )
        assert len(fallbacks) == 1
        assert fallbacks[0].name == "modal"

    def test_set_enabled(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test enabling/disabling providers."""
        assert populated_registry.set_enabled("kubernetes", enabled=False) is True
        provider = populated_registry.get_enabled_provider("kubernetes")
        assert provider is None

        assert populated_registry.set_enabled("kubernetes", enabled=True) is True
        provider = populated_registry.get_enabled_provider("kubernetes")
        assert provider is not None

    def test_set_enabled_nonexistent_provider(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test setting enabled on nonexistent provider returns False."""
        result = populated_registry.set_enabled("nonexistent", enabled=False)
        assert result is False

    def test_contains(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test __contains__ operator."""
        assert "kubernetes" in populated_registry
        assert "modal" in populated_registry
        assert "nonexistent" not in populated_registry

    def test_len(
        self,
        populated_registry: MLProviderRegistry,
    ) -> None:
        """Test __len__ operator."""
        assert len(populated_registry) == 2

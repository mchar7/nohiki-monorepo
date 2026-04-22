"""Tests for provider discovery."""

from __future__ import annotations

from ml_gateway_service.providers.discovery import discover_providers
from ml_gateway_service.providers.kubernetes import KubernetesMLProvider
from ml_gateway_service.providers.modal import ModalMLProvider


class TestDiscoverProviders:
    """Tests for discover_providers function."""

    def test_discovers_kubernetes_and_modal(self) -> None:
        """Test that discovery finds both Kubernetes and Modal providers."""
        providers = discover_providers()
        assert len(providers) == 2

        provider_names = {p.name for p in providers}
        assert "kubernetes" in provider_names
        assert "modal" in provider_names

    def test_returns_provider_instances(self) -> None:
        """Test that discovery returns actual provider instances."""
        providers = discover_providers()
        assert all(hasattr(p, "name") for p in providers)
        assert all(hasattr(p, "capabilities") for p in providers)
        assert all(hasattr(p, "get_target_topic") for p in providers)

    def test_kubernetes_provider_type(self) -> None:
        """Test that Kubernetes provider is correct type."""
        providers = discover_providers()
        k8s_provider = next(p for p in providers if p.name == "kubernetes")
        assert isinstance(k8s_provider, KubernetesMLProvider)

    def test_modal_provider_type(self) -> None:
        """Test that Modal provider is correct type."""
        providers = discover_providers()
        modal_provider = next(p for p in providers if p.name == "modal")
        assert isinstance(modal_provider, ModalMLProvider)

    def test_providers_are_unique_instances(self) -> None:
        """Test that each call returns new instances."""
        providers1 = discover_providers()
        providers2 = discover_providers()
        assert providers1[0] is not providers2[0]
        assert providers1[1] is not providers2[1]

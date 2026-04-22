"""Tests for MLProviderRegistry singleton."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ml_gateway_service.providers.registry import _RegistryHolder, get_provider_registry


class TestRegistrySingleton:
    """Tests for registry singleton pattern."""

    def test_get_provider_registry_returns_registry(self) -> None:
        """Test that get_provider_registry returns a registry instance."""
        registry = get_provider_registry()
        assert registry is not None
        assert len(registry) == 2  # K8s and Modal from discovery

    def test_get_provider_registry_returns_same_instance(self) -> None:
        """Test that get_provider_registry returns the same instance."""
        registry1 = get_provider_registry()
        registry2 = get_provider_registry()
        assert registry1 is registry2

    def test_reset_clears_singleton(self) -> None:
        """Test that reset clears the singleton."""
        registry1 = get_provider_registry()
        _RegistryHolder.reset()
        registry2 = get_provider_registry()
        assert registry1 is not registry2

    @patch("ml_gateway_service.providers.registry.discover_providers")
    @patch("ml_gateway_service.providers.registry.get_settings")
    def test_create_populates_from_discovery(
        self,
        mock_get_settings: MagicMock,
        mock_discover: MagicMock,
    ) -> None:
        """Test that _create populates registry from discovery."""
        from ml_gateway_service.providers.kubernetes import KubernetesMLProvider
        from ml_gateway_service.providers.modal import ModalMLProvider

        # Mock settings
        mock_settings = MagicMock()
        mock_settings.provider_registry.providers = []
        mock_get_settings.return_value = mock_settings

        # Mock discovery
        mock_discover.return_value = [
            KubernetesMLProvider(),
            ModalMLProvider(),
        ]

        _RegistryHolder.reset()
        registry = get_provider_registry()

        assert len(registry) == 2
        assert "kubernetes" in registry
        assert "modal" in registry

    @patch("ml_gateway_service.providers.registry.discover_providers")
    @patch("ml_gateway_service.providers.registry.get_settings")
    def test_create_uses_config_priority(
        self,
        mock_get_settings: MagicMock,
        mock_discover: MagicMock,
    ) -> None:
        """Test that _create uses config priority when provided."""
        from ml_gateway_service.providers.kubernetes import KubernetesMLProvider

        # Mock settings with custom priority
        mock_config = MagicMock()
        mock_config.name = "kubernetes"
        mock_config.priority = 99
        mock_config.enabled = False

        mock_settings = MagicMock()
        mock_settings.provider_registry.providers = [mock_config]
        mock_get_settings.return_value = mock_settings

        # Mock discovery
        mock_discover.return_value = [KubernetesMLProvider()]

        _RegistryHolder.reset()
        registry = get_provider_registry()

        # Verify custom config was used
        provider = registry.get_provider("kubernetes")
        assert provider is not None
        # Provider should be disabled per config
        enabled_provider = registry.get_enabled_provider("kubernetes")
        assert enabled_provider is None

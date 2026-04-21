"""Provider registry for managing ML routing providers.

Architecture: ml-gateway-service is ROUTING ONLY. The registry selects providers
based on operation type and capabilities. Providers return target Kafka topics.
"""

from __future__ import annotations

from dataclasses import dataclass

from nohiki_observability import get_logger

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.providers.base import BaseMLProvider, MLOperationType
from ml_gateway_service.providers.discovery import discover_providers

logger = get_logger(__name__)


@dataclass(slots=True)
class RegisteredProvider:
    """A provider with its configuration and priority."""

    provider: BaseMLProvider
    priority: int = 100
    enabled: bool = True


class MLProviderRegistry:
    """Registry for ML compute providers with operation-based selection.

    Supports multiple providers with priority-based selection per operation type.
    For example, Kubernetes is preferred for embeddings (cost-effective), while
    Modal is required for reranking (GPU needed).
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: dict[str, RegisteredProvider] = {}
        self._operation_to_providers: dict[MLOperationType, list[RegisteredProvider]] = {
            op: [] for op in MLOperationType
        }

    def register(
        self,
        provider: BaseMLProvider,
        *,
        priority: int = 100,
        enabled: bool = True,
    ) -> None:
        """Register a provider.

        Args:
            provider: Provider instance to register.
            priority: Lower values = higher priority (checked first).
            enabled: Whether this provider is currently enabled.

        Raises:
            ValueError: If provider name already registered.

        """
        if provider.name in self._providers:
            msg = f"Provider '{provider.name}' already registered"
            raise ValueError(msg)

        registered = RegisteredProvider(
            provider=provider,
            priority=priority,
            enabled=enabled,
        )

        self._providers[provider.name] = registered

        # Index by supported operations
        for operation in MLOperationType:
            if provider.supports_operation(operation):
                self._operation_to_providers[operation].append(registered)
                self._sort_providers_for_operation(operation)

        logger.info(
            "Registered ML provider",
            provider=provider.name,
            priority=priority,
            enabled=enabled,
            capabilities=provider.capabilities,
        )

    def _sort_providers_for_operation(self, operation: MLOperationType) -> None:
        """Sort providers for an operation by priority (lower = first)."""
        self._operation_to_providers[operation].sort(key=lambda r: r.priority)

    def get_provider_for_operation(
        self,
        operation: MLOperationType,
        *,
        require_gpu: bool = False,
    ) -> BaseMLProvider | None:
        """Get the highest-priority enabled provider for an operation.

        Args:
            operation: Type of ML operation.
            require_gpu: If True, only return providers with GPU capability.

        Returns:
            Best provider for the operation, or None if none available.

        """
        for registered in self._operation_to_providers.get(operation, []):
            if not registered.enabled:
                continue
            if require_gpu and not registered.provider.capabilities.gpu_available:
                continue
            return registered.provider
        return None

    def get_provider(self, name: str) -> BaseMLProvider | None:
        """Get provider by name (regardless of enabled status)."""
        registered = self._providers.get(name)
        return registered.provider if registered else None

    def get_enabled_provider(self, name: str) -> BaseMLProvider | None:
        """Get provider by name only if enabled."""
        registered = self._providers.get(name)
        if registered and registered.enabled:
            return registered.provider
        return None

    def get_all_providers(self, *, enabled_only: bool = True) -> list[BaseMLProvider]:
        """Get all registered providers ordered by priority.

        Args:
            enabled_only: If True, only return enabled providers.

        Returns:
            List of providers ordered by priority (highest first).

        """
        registered_list = sorted(
            self._providers.values(),
            key=lambda r: r.priority,
        )
        if enabled_only:
            return [r.provider for r in registered_list if r.enabled]
        return [r.provider for r in registered_list]

    def get_primary_provider(self) -> BaseMLProvider | None:
        """Get the highest-priority enabled provider."""
        providers = self.get_all_providers(enabled_only=True)
        return providers[0] if providers else None

    def get_fallback_providers(
        self,
        operation: MLOperationType,
        *,
        exclude: str | None = None,
    ) -> list[BaseMLProvider]:
        """Get fallback providers for an operation.

        Args:
            operation: Type of ML operation.
            exclude: Provider name to exclude from results.

        Returns:
            List of fallback providers ordered by priority.

        """
        providers = []
        for registered in self._operation_to_providers.get(operation, []):
            if not registered.enabled:
                continue
            if exclude and registered.provider.name == exclude:
                continue
            providers.append(registered.provider)
        return providers[1:] if providers and not exclude else providers

    def set_enabled(self, name: str, *, enabled: bool) -> bool:
        """Enable or disable a provider.

        Args:
            name: Provider name.
            enabled: New enabled status.

        Returns:
            True if provider was found and updated, False otherwise.

        """
        registered = self._providers.get(name)
        if registered:
            registered.enabled = enabled
            logger.info("Provider status changed", provider=name, enabled=enabled)
            return True
        return False

    def __contains__(self, name: str) -> bool:
        """Check if provider is registered by name."""
        return name in self._providers

    def __len__(self) -> int:
        """Return number of registered providers."""
        return len(self._providers)


class _RegistryHolder:
    """Holder for lazy-initialized singleton registry."""

    _instance: MLProviderRegistry | None = None

    @classmethod
    def get(cls) -> MLProviderRegistry:
        """Get or create the registry singleton."""
        if cls._instance is None:
            cls._instance = cls._create()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    @classmethod
    def _create(cls) -> MLProviderRegistry:
        """Create and populate the registry using auto-discovery."""
        registry = MLProviderRegistry()
        settings = get_settings()
        config_by_name = {cfg.name: cfg for cfg in settings.provider_registry.providers}

        for provider in discover_providers():
            config = config_by_name.get(provider.name)
            registry.register(
                provider,
                priority=config.priority if config else provider.default_priority(),
                enabled=config.enabled if config else provider.default_enabled(),
            )

        return registry


def get_provider_registry() -> MLProviderRegistry:
    """Get the global provider registry."""
    return _RegistryHolder.get()

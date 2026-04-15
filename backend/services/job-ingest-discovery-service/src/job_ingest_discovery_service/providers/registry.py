"""Provider registry for managing discovery providers.

The registry maintains a collection of providers and handles routing
discovery requests to the appropriate provider(s) based on requested sources.
Supports multiple providers per source with priority-based selection.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from functools import total_ordering

from nohiki.common.v1 import JobBoardSource
from nohiki_observability import get_logger

from job_ingest_discovery_service.core.config import get_settings
from job_ingest_discovery_service.providers.base import BaseProvider
from job_ingest_discovery_service.providers.discovery import discover_providers

logger = get_logger(__name__)


@total_ordering
@dataclass(eq=False)
class RegisteredProvider:
    """A provider with its configuration and priority."""

    provider: BaseProvider
    priority: int = 100
    enabled: bool = True

    def __lt__(self, other: object) -> bool:
        """Compare by priority for bisect ordering."""
        if not isinstance(other, RegisteredProvider):
            return NotImplemented
        return self.priority < other.priority

    def __eq__(self, other: object) -> bool:
        """Check equality by priority for bisect ordering."""
        if not isinstance(other, RegisteredProvider):
            return NotImplemented
        return self.priority == other.priority

    def __hash__(self) -> int:
        """Hash by provider name for dict storage."""
        return hash(self.provider.name)


class ProviderRegistry:
    """Registry for job scraping providers.

    Supports multiple providers per source with priority-based selection.
    Providers are discovered automatically and filtered by configuration.
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._providers: dict[str, RegisteredProvider] = {}
        self._source_to_providers: dict[JobBoardSource, list[RegisteredProvider]] = {}

    def register(
        self,
        provider: BaseProvider,
        *,
        priority: int = 100,
        enabled: bool = True,
        sources: list[JobBoardSource] | None = None,
    ) -> None:
        """Register a provider.

        Args:
            provider: Provider instance to register.
            priority: Lower values = higher priority (checked first).
            enabled: Whether this provider is currently enabled.
            sources: Optional override of provider supported sources.

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

        supported_sources = sources if sources is not None else provider.supported_sources

        for source in supported_sources:
            bisect.insort(self._source_to_providers.setdefault(source, []), registered)

        logger.info(
            "Registered provider",
            provider=provider.name,
            priority=priority,
            enabled=enabled,
            sources=[s.name for s in supported_sources],
        )

    def get_provider(self, name: str) -> BaseProvider | None:
        """Get provider by name (regardless of enabled status)."""
        registered = self._providers.get(name)
        return registered.provider if registered else None

    def get_enabled_provider(self, name: str) -> BaseProvider | None:
        """Get provider by name only if enabled."""
        registered = self._providers.get(name)
        if registered and registered.enabled:
            return registered.provider
        return None

    def get_providers_for_source(
        self,
        source: JobBoardSource,
        *,
        enabled_only: bool = True,
    ) -> list[BaseProvider]:
        """Get all providers for a source, ordered by priority.

        Args:
            source: Source type to find providers for.
            enabled_only: If True, only return enabled providers.

        Returns:
            List of providers ordered by priority (highest first).

        """
        registered_list = self._source_to_providers.get(source, [])
        if enabled_only:
            return [r.provider for r in registered_list if r.enabled]
        return [r.provider for r in registered_list]

    def get_primary_provider_for_source(
        self,
        source: JobBoardSource,
    ) -> BaseProvider | None:
        """Get the highest-priority enabled provider for a source."""
        providers = self.get_providers_for_source(source, enabled_only=True)
        return providers[0] if providers else None

    def get_fallback_providers_for_source(
        self,
        source: JobBoardSource,
        *,
        exclude: str | None = None,
    ) -> list[BaseProvider]:
        """Get fallback providers for a source (excluding primary or specified).

        Args:
            source: Source type to find fallback providers for.
            exclude: Provider name to exclude from results.

        Returns:
            List of fallback providers ordered by priority.

        """
        providers = self.get_providers_for_source(source, enabled_only=True)
        if exclude:
            return [p for p in providers if p.name != exclude]
        return providers[1:] if len(providers) > 1 else []

    def get_providers_for_sources(
        self,
        sources: list[JobBoardSource],
    ) -> list[BaseProvider]:
        """Get unique enabled providers that can handle the requested sources.

        Args:
            sources: List of source types to find providers for.

        Returns:
            List of unique providers (no duplicates).

        """
        seen: set[str] = set()
        providers: list[BaseProvider] = []

        for source in sources:
            for provider in self.get_providers_for_source(source):
                if provider.name not in seen:
                    seen.add(provider.name)
                    providers.append(provider)

        return providers

    def get_all_providers(self, *, enabled_only: bool = True) -> list[BaseProvider]:
        """Get all registered providers."""
        if enabled_only:
            return [r.provider for r in self._providers.values() if r.enabled]
        return [r.provider for r in self._providers.values()]

    def get_all_sources(self) -> list[JobBoardSource]:
        """Get all supported source types."""
        return list(self._source_to_providers.keys())

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

    _instance: ProviderRegistry | None = None

    @classmethod
    def get(cls) -> ProviderRegistry:
        """Get or create the registry singleton."""
        if cls._instance is None:
            cls._instance = cls._create()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    @classmethod
    def _create(cls) -> ProviderRegistry:
        """Create and populate the registry using auto-discovery."""
        registry = ProviderRegistry()

        settings = get_settings()
        config_by_name = {cfg.name: cfg for cfg in settings.provider_registry.providers}

        source_by_name = {s.name: s for s in JobBoardSource}

        for provider in discover_providers():
            config = config_by_name.get(provider.name)

            sources: list[JobBoardSource] | None = None
            if config is not None and config.sources:
                sources = [source_by_name[s] for s in config.sources if s in source_by_name]
            if sources is None:
                sources = provider.default_sources_override()

            registry.register(
                provider,
                priority=config.priority if config is not None else provider.default_priority(),
                enabled=config.enabled if config is not None else provider.default_enabled(),
                sources=sources,
            )

        return registry


def get_provider_registry() -> ProviderRegistry:
    """Get the global provider registry."""
    return _RegistryHolder.get()

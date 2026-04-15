"""Tests for provider registry."""

from __future__ import annotations

import pytest
from job_ingest_discovery_service.core.models import DiscoveryRequest, DiscoveryResult
from job_ingest_discovery_service.providers.base import BaseProvider
from job_ingest_discovery_service.providers.registry import (
    ProviderRegistry,
    _RegistryHolder,
)
from nohiki.common.v1 import JobBoardSource


class MockProvider(BaseProvider):
    """Mock provider for testing."""

    def __init__(
        self,
        name: str = "mock",
        sources: list[JobBoardSource] | None = None,
    ) -> None:
        """Initialize the mock provider."""
        self._name = name
        self._sources = sources or [JobBoardSource.INDEED]

    @property
    def name(self) -> str:
        return self._name

    @property
    def supported_sources(self) -> list[JobBoardSource]:
        return self._sources

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        return DiscoveryResult(listings=[], provider_name=self.name)


class TestProviderRegistry:
    """Tests for ProviderRegistry class."""

    def test_register_provider(self) -> None:
        """Test registering a provider."""
        registry = ProviderRegistry()
        provider = MockProvider()

        registry.register(provider)

        assert "mock" in registry
        assert len(registry) == 1

    def test_register_with_priority(self) -> None:
        """Test registering with custom priority."""
        registry = ProviderRegistry()
        provider = MockProvider()

        registry.register(provider, priority=10, enabled=True)

        assert "mock" in registry

    def test_register_duplicate_name_raises(self) -> None:
        """Test that duplicate names raise ValueError."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="test"))

        with pytest.raises(ValueError, match="already registered"):
            registry.register(MockProvider(name="test"))

    def test_get_provider_by_name(self) -> None:
        """Test getting provider by name."""
        registry = ProviderRegistry()
        provider = MockProvider(name="test")
        registry.register(provider)

        result = registry.get_provider("test")
        assert result is provider

    def test_get_provider_not_found(self) -> None:
        """Test getting non-existent provider returns None."""
        registry = ProviderRegistry()
        assert registry.get_provider("nonexistent") is None

    def test_get_enabled_provider(self) -> None:
        """Test getting enabled provider."""
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider, enabled=True)

        assert registry.get_enabled_provider("mock") is provider

    def test_get_enabled_provider_when_disabled(self) -> None:
        """Test getting disabled provider returns None."""
        registry = ProviderRegistry()
        provider = MockProvider()
        registry.register(provider, enabled=False)

        assert registry.get_enabled_provider("mock") is None


class TestProviderRegistryMultipleProviders:
    """Tests for multiple providers per source."""

    def test_multiple_providers_same_source(self) -> None:
        """Test registering multiple providers for same source."""
        registry = ProviderRegistry()
        provider1 = MockProvider(name="provider1", sources=[JobBoardSource.INDEED])
        provider2 = MockProvider(name="provider2", sources=[JobBoardSource.INDEED])

        registry.register(provider1, priority=10)
        registry.register(provider2, priority=20)

        providers = registry.get_providers_for_source(JobBoardSource.INDEED)
        assert len(providers) == 2
        assert providers[0].name == "provider1"  # Lower priority first
        assert providers[1].name == "provider2"

    def test_primary_provider_is_highest_priority(self) -> None:
        """Test primary provider is the one with lowest priority value."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="low", sources=[JobBoardSource.INDEED]), priority=100)
        registry.register(MockProvider(name="high", sources=[JobBoardSource.INDEED]), priority=10)

        primary = registry.get_primary_provider_for_source(JobBoardSource.INDEED)
        assert primary is not None
        assert primary.name == "high"

    def test_fallback_providers_exclude_primary(self) -> None:
        """Test fallback providers exclude the primary."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="primary", sources=[JobBoardSource.INDEED]), priority=10)
        registry.register(MockProvider(name="fallback1", sources=[JobBoardSource.INDEED]), priority=20)
        registry.register(MockProvider(name="fallback2", sources=[JobBoardSource.INDEED]), priority=30)

        fallbacks = registry.get_fallback_providers_for_source(JobBoardSource.INDEED)
        assert len(fallbacks) == 2
        assert fallbacks[0].name == "fallback1"
        assert fallbacks[1].name == "fallback2"

    def test_fallback_with_exclude(self) -> None:
        """Test fallback with explicit exclude."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="a", sources=[JobBoardSource.INDEED]), priority=10)
        registry.register(MockProvider(name="b", sources=[JobBoardSource.INDEED]), priority=20)
        registry.register(MockProvider(name="c", sources=[JobBoardSource.INDEED]), priority=30)

        fallbacks = registry.get_fallback_providers_for_source(
            JobBoardSource.INDEED,
            exclude="b",
        )
        assert len(fallbacks) == 2
        assert "b" not in [p.name for p in fallbacks]


class TestProviderRegistryEnabledFiltering:
    """Tests for enabled/disabled filtering."""

    def test_get_providers_for_source_enabled_only(self) -> None:
        """Test filtering by enabled status."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="enabled"), enabled=True)
        registry.register(MockProvider(name="disabled"), enabled=False)

        providers = registry.get_providers_for_source(JobBoardSource.INDEED, enabled_only=True)
        assert len(providers) == 1
        assert providers[0].name == "enabled"

    def test_get_providers_for_source_all(self) -> None:
        """Test getting all providers regardless of status."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="enabled"), enabled=True)
        registry.register(MockProvider(name="disabled"), enabled=False)

        providers = registry.get_providers_for_source(JobBoardSource.INDEED, enabled_only=False)
        assert len(providers) == 2

    def test_set_enabled(self) -> None:
        """Test enabling/disabling a provider."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="test"), enabled=True)

        assert registry.get_enabled_provider("test") is not None

        registry.set_enabled("test", enabled=False)
        assert registry.get_enabled_provider("test") is None

        registry.set_enabled("test", enabled=True)
        assert registry.get_enabled_provider("test") is not None

    def test_set_enabled_nonexistent(self) -> None:
        """Test set_enabled returns False for nonexistent provider."""
        registry = ProviderRegistry()
        result = registry.set_enabled("nonexistent", enabled=True)
        assert result is False


class TestProviderRegistrySourceQueries:
    """Tests for source-based queries."""

    def test_get_providers_for_sources(self) -> None:
        """Test getting unique providers for multiple sources."""
        registry = ProviderRegistry()
        # Provider handling multiple sources
        multi = MockProvider(
            name="multi",
            sources=[JobBoardSource.INDEED, JobBoardSource.LINKEDIN],
        )
        # Provider handling single source
        single = MockProvider(name="single", sources=[JobBoardSource.GLASSDOOR])

        registry.register(multi)
        registry.register(single)

        providers = registry.get_providers_for_sources(
            [
                JobBoardSource.INDEED,
                JobBoardSource.LINKEDIN,
                JobBoardSource.GLASSDOOR,
            ]
        )

        assert len(providers) == 2
        names = [p.name for p in providers]
        assert "multi" in names
        assert "single" in names

    def test_get_all_sources(self) -> None:
        """Test getting all supported sources."""
        registry = ProviderRegistry()
        registry.register(MockProvider(sources=[JobBoardSource.INDEED, JobBoardSource.LINKEDIN]))

        sources = registry.get_all_sources()
        assert JobBoardSource.INDEED in sources
        assert JobBoardSource.LINKEDIN in sources

    def test_get_all_providers(self) -> None:
        """Test getting all providers."""
        registry = ProviderRegistry()
        registry.register(MockProvider(name="a"), enabled=True)
        registry.register(MockProvider(name="b"), enabled=False)

        all_enabled = registry.get_all_providers(enabled_only=True)
        assert len(all_enabled) == 1

        all_providers = registry.get_all_providers(enabled_only=False)
        assert len(all_providers) == 2


class TestRegistryHolder:
    """Tests for _RegistryHolder singleton."""

    def test_reset_clears_instance(self) -> None:
        """Test that reset clears the singleton."""
        # Set a dummy instance to test reset
        _RegistryHolder._instance = ProviderRegistry()

        # Reset
        _RegistryHolder.reset()

        # Verify reset worked (instance is None)
        assert _RegistryHolder._instance is None

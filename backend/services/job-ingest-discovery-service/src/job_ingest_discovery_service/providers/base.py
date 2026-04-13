"""Abstract base class for job discovery providers.

Providers implement this interface to integrate with different job boards
or discovery libraries. The discovery service orchestrates multiple providers
without knowing their implementation details.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextvars import ContextVar, Token

from nohiki.common.v1 import JobBoardSource

from job_ingest_discovery_service.core.config import ProviderFallbackSettings
from job_ingest_discovery_service.core.models import DiscoveryRequest, DiscoveryResult

_leaf_fetch_limiter: ContextVar[asyncio.Semaphore | None] = ContextVar("job_ingest_leaf_fetch_limiter", default=None)


def get_leaf_fetch_limiter() -> asyncio.Semaphore | None:
    """Return the discovery command's shared blocking-fetch limiter."""
    return _leaf_fetch_limiter.get()


def set_leaf_fetch_limiter(limiter: asyncio.Semaphore) -> Token[asyncio.Semaphore | None]:
    """Set the shared blocking-fetch limiter for the current discovery command."""
    return _leaf_fetch_limiter.set(limiter)


def reset_leaf_fetch_limiter(token: Token[asyncio.Semaphore | None]) -> None:
    """Restore the previous blocking-fetch limiter context."""
    _leaf_fetch_limiter.reset(token)


class BaseProvider(ABC):
    """Abstract base class for job discovery providers.

    Each provider implementation handles a specific job board or discovery
    library. Providers are responsible for:
    - Mapping DiscoveryRequest parameters to their API requirements
    - Executing the discovery operation
    - Mapping results to RawListing internal models
    - Handling provider-specific errors and rate limiting

    Providers output RawListing (internal model), NOT DiscoveredListing (proto).
    Conversion to proto happens centrally in listing_factory.py.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this provider."""

    @property
    @abstractmethod
    def supported_sources(self) -> list[JobBoardSource]:
        """List of job board sources this provider can discover from."""

    @abstractmethod
    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        """Execute a discovery operation.

        Args:
            request: Source-agnostic discovery request.

        Returns:
            DiscoveryResult containing RawListing internal models.

        Note:
            Implementations should handle errors gracefully and return
            a DiscoveryResult with error information rather than raising.

        """

    def supports_source(self, source: JobBoardSource) -> bool:
        """Check if this provider supports the given source."""
        return source in self.supported_sources

    def default_enabled(self) -> bool:
        """Return default enabled status when no explicit config is provided."""
        return False

    def default_priority(self) -> int:
        """Return default priority when no explicit config is provided."""
        return 999

    def default_sources_override(self) -> list[JobBoardSource] | None:
        """Return optional override for supported sources."""
        return None

    def default_fallback_settings(self) -> ProviderFallbackSettings:
        """Return default fallback settings."""
        return ProviderFallbackSettings()

    async def health_check(self) -> bool:
        """Check if the provider is healthy and ready."""
        await asyncio.sleep(0)
        return True

    def __repr__(self) -> str:
        """Return string representation of provider."""
        sources = [s.name for s in self.supported_sources]
        return f"{self.__class__.__name__}(name={self.name!r}, sources={sources})"

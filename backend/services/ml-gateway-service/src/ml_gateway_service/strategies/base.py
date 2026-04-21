"""Base class for provider routing strategies."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ml_gateway_service.providers.base import BaseMLProvider
    from ml_gateway_service.providers.registry import MLProviderRegistry


class BaseRoutingStrategy(ABC):
    """Abstract base class for provider routing strategies.

    Strategies determine how the gateway selects providers for ML requests.
    """

    @abstractmethod
    async def select_provider(
        self,
        registry: MLProviderRegistry,
    ) -> BaseMLProvider | None:
        """Select a provider for the next request.

        Args:
            registry: Provider registry to select from.

        Returns:
            Selected provider, or None if no provider available.

        """

    @abstractmethod
    async def should_fallback(
        self,
        provider: BaseMLProvider,
        error_code: str | None,
        retry_after_seconds: float | None,
    ) -> bool:
        """Determine if we should fallback to next provider.

        Args:
            provider: Provider that failed.
            error_code: Error code from provider (e.g., 'rate_limited').
            retry_after_seconds: Retry-After value if rate limited.

        Returns:
            True if should fallback to next provider.

        """

    async def clear_provider_state(self, provider_name: str) -> None:
        """Clear provider state on success.

        Override to implement state tracking cleanup. Default is no-op.

        Args:
            provider_name: Name of provider to clear state for.

        """
        _ = provider_name
        await asyncio.sleep(0)

"""Explicit provider routing strategy."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.strategies.base import BaseRoutingStrategy

if TYPE_CHECKING:
    from ml_gateway_service.providers.base import BaseMLProvider
    from ml_gateway_service.providers.registry import MLProviderRegistry

logger = get_logger(__name__)


class ExplicitProviderStrategy(BaseRoutingStrategy):
    """Explicit provider routing strategy.

    Uses one provider only; no fallback.
    Use case: Testing, cost control, explicit provider requirement.
    """

    def __init__(self, provider_name: str | None = None) -> None:
        """Initialize explicit strategy.

        Args:
            provider_name: Provider name to use (from config if None).

        """
        self._provider_name = provider_name or get_settings().provider_registry.explicit_provider_name

    async def select_provider(
        self,
        registry: MLProviderRegistry,
    ) -> BaseMLProvider | None:
        """Select the explicitly configured provider."""
        if self._provider_name is None:
            logger.error("Explicit strategy requires provider_name to be configured")
            return None

        provider = registry.get_enabled_provider(self._provider_name)
        if provider is None:
            logger.error(
                "Explicitly configured provider not available",
                provider_name=self._provider_name,
            )
        return provider

    async def should_fallback(
        self,
        provider: BaseMLProvider,
        error_code: str | None,
        retry_after_seconds: float | None,
    ) -> bool:
        """Explicit strategy never falls back."""
        del provider, error_code, retry_after_seconds  # Unused but required by interface
        await asyncio.sleep(0)
        return False

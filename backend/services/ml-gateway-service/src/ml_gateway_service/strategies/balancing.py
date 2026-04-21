"""Load balancing routing strategy."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from nohiki_redis_utils import create_cache, make_cache_key

from ml_gateway_service.core.config import get_settings
from ml_gateway_service.strategies.base import BaseRoutingStrategy

if TYPE_CHECKING:
    from ml_gateway_service.providers.base import BaseMLProvider
    from ml_gateway_service.providers.registry import MLProviderRegistry

logger = get_logger(__name__)
settings = get_settings()
_cache = create_cache(settings.service_name, redis_url=settings.redis.connection_string)
_COUNTER_TTL_SECONDS = 60 * 60


class LoadBalancingStrategy(BaseRoutingStrategy):
    """Load balancing routing strategy.

    Distributes requests across enabled providers via round-robin.
    Use case: Distribute load evenly across registered providers.
    """

    async def select_provider(
        self,
        registry: MLProviderRegistry,
    ) -> BaseMLProvider | None:
        """Select provider via round-robin."""
        providers = registry.get_all_providers(enabled_only=True)
        if not providers:
            return None

        if len(providers) == 1:
            return providers[0]

        counter_key = make_cache_key("ml_provider_balancing_counter")
        counter = await _cache.get(counter_key)

        current_idx = int(counter) if isinstance(counter, (int, str)) else 0
        selected_idx = current_idx % len(providers)

        await _cache.set(counter_key, current_idx + 1, ttl=_COUNTER_TTL_SECONDS)

        return providers[selected_idx]

    async def should_fallback(
        self,
        provider: BaseMLProvider,
        error_code: str | None,
        retry_after_seconds: float | None,
    ) -> bool:
        """Load balancing strategy does not fallback.

        Each request gets a provider via round-robin; failures are retried
        by Kafka consumer, which will select a different provider next time.
        """
        del provider, error_code, retry_after_seconds  # Unused but required by interface
        await asyncio.sleep(0)
        return False

"""Dynamic fallback routing strategy (default)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from nohiki_observability import get_logger
from nohiki_redis_utils import create_cache, make_cache_key

from ml_gateway_service.core.config import ProviderConfigSettings, get_settings
from ml_gateway_service.strategies.base import BaseRoutingStrategy

if TYPE_CHECKING:
    from ml_gateway_service.providers.base import BaseMLProvider
    from ml_gateway_service.providers.registry import MLProviderRegistry

logger = get_logger(__name__)
settings = get_settings()
_cache = create_cache(settings.service_name, redis_url=settings.redis_url)


class DynamicFallbackStrategy(BaseRoutingStrategy):
    """Dynamic fallback routing strategy.

    - Uses highest-priority enabled provider
    - Falls back to next provider on sustained errors
    - Tracks provider health in Redis cache
    """

    async def select_provider(
        self,
        registry: MLProviderRegistry,
    ) -> BaseMLProvider | None:
        """Select provider with fallback on errors."""
        providers = registry.get_all_providers(enabled_only=True)
        if not providers:
            return None

        return providers[0]

    async def should_fallback(
        self,
        provider: BaseMLProvider,
        error_code: str | None,
        retry_after_seconds: float | None,
    ) -> bool:
        """Determine if we should fallback to next provider.

        Fallback conditions:
        - Rate limited with long wait time
        - Sustained errors over threshold
        """
        config = self._get_effective_provider_config(provider)
        if not config.fallback.enabled:
            return False

        if error_code == "rate_limited":
            if retry_after_seconds is None:
                return False
            return retry_after_seconds > float(config.fallback.rate_limit_wait_threshold_seconds)

        consecutive_errors, duration_seconds = await self._record_provider_error(provider.name)
        if consecutive_errors < int(config.fallback.min_consecutive_errors):
            return False
        return duration_seconds >= float(config.fallback.error_duration_threshold_seconds)

    async def clear_provider_state(self, provider_name: str) -> None:
        """Clear provider error state on success."""
        await _cache.delete(self._make_fallback_state_key(provider_name))

    def _get_effective_provider_config(
        self,
        provider: BaseMLProvider,
    ) -> ProviderConfigSettings:
        """Get provider config from settings or defaults."""
        config_by_name = {cfg.name: cfg for cfg in settings.provider_registry.providers}
        cfg = config_by_name.get(provider.name)

        if cfg is not None:
            return cfg

        return ProviderConfigSettings(
            name=provider.name,
            enabled=provider.default_enabled(),
            priority=provider.default_priority(),
            fallback=provider.default_fallback_settings(),
        )

    def _make_fallback_state_key(self, provider_name: str) -> str:
        return make_cache_key("ml_provider_fallback", provider_name)

    async def _record_provider_error(self, provider_name: str) -> tuple[int, float]:
        """Record provider error and return (consecutive_errors, duration_seconds)."""
        now = time.time()
        key = self._make_fallback_state_key(provider_name)
        state_obj = await _cache.get(key)

        state: dict[str, float | int] = cast(dict[str, float | int], state_obj) if isinstance(state_obj, dict) else {}

        first_error_at = float(state.get("first_error_at", now))
        last_error_at = float(state.get("last_error_at", now))
        consecutive_errors = int(state.get("consecutive_errors", 0))

        if consecutive_errors == 0 or last_error_at == 0:
            first_error_at = now

        consecutive_errors += 1
        last_error_at = now

        await _cache.set(
            key,
            {
                "first_error_at": first_error_at,
                "last_error_at": last_error_at,
                "consecutive_errors": consecutive_errors,
            },
            ttl=settings.caching.provider_fallback_state_ttl_seconds,
        )

        return consecutive_errors, now - first_error_at

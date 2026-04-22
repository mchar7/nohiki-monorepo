"""Unit tests for ml_gateway_service.strategies module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ml_gateway_service.strategies.balancing import LoadBalancingStrategy
from ml_gateway_service.strategies.base import BaseRoutingStrategy
from ml_gateway_service.strategies.dynamic import DynamicFallbackStrategy
from ml_gateway_service.strategies.explicit import ExplicitProviderStrategy


class TestBaseRoutingStrategy:
    """Tests for BaseRoutingStrategy ABC."""

    def test_is_abstract(self) -> None:
        """BaseRoutingStrategy is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseRoutingStrategy()

    @pytest.mark.asyncio
    async def test_clear_provider_state_default_is_noop(self) -> None:
        """Default clear_provider_state does nothing."""
        from ml_gateway_service.providers.base import BaseMLProvider
        from ml_gateway_service.providers.registry import MLProviderRegistry

        class ConcreteStrategy(BaseRoutingStrategy):
            async def select_provider(self, registry: MLProviderRegistry) -> BaseMLProvider | None:
                return None

            async def should_fallback(
                self,
                provider: BaseMLProvider,
                error_code: str | None,
                retry_after_seconds: float | None,
            ) -> bool:
                return False

        strategy = ConcreteStrategy()
        await strategy.clear_provider_state("test_provider")


class TestLoadBalancingStrategy:
    """Tests for LoadBalancingStrategy."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_providers(self) -> None:
        """Returns None when no providers available."""
        strategy = LoadBalancingStrategy()
        mock_registry = MagicMock()
        mock_registry.get_all_providers.return_value = []

        result = await strategy.select_provider(mock_registry)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_single_provider_directly(self) -> None:
        """Returns single provider without round-robin."""
        strategy = LoadBalancingStrategy()
        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_registry.get_all_providers.return_value = [mock_provider]

        result = await strategy.select_provider(mock_registry)

        assert result is mock_provider

    @pytest.mark.asyncio
    async def test_round_robin_with_multiple_providers(self) -> None:
        """Distributes requests across providers via round-robin."""
        strategy = LoadBalancingStrategy()
        mock_registry = MagicMock()
        provider1 = MagicMock(name="provider1")
        provider2 = MagicMock(name="provider2")
        mock_registry.get_all_providers.return_value = [provider1, provider2]

        with patch("ml_gateway_service.strategies.balancing._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=0)
            mock_cache.set = AsyncMock()

            result = await strategy.select_provider(mock_registry)

            assert result is provider1
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_fallback_always_false(self) -> None:
        """Load balancing strategy never falls back."""
        strategy = LoadBalancingStrategy()
        mock_provider = MagicMock()

        result = await strategy.should_fallback(mock_provider, "rate_limited", 60.0)

        assert result is False

    @pytest.mark.asyncio
    async def test_should_fallback_with_none_values(self) -> None:
        """Load balancing handles None error_code and retry_after."""
        strategy = LoadBalancingStrategy()
        mock_provider = MagicMock()

        result = await strategy.should_fallback(mock_provider, None, None)

        assert result is False


class TestDynamicFallbackStrategy:
    """Tests for DynamicFallbackStrategy."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_providers(self) -> None:
        """Returns None when no providers available."""
        strategy = DynamicFallbackStrategy()
        mock_registry = MagicMock()
        mock_registry.get_all_providers.return_value = []

        result = await strategy.select_provider(mock_registry)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_first_provider(self) -> None:
        """Returns highest priority (first) provider."""
        strategy = DynamicFallbackStrategy()
        mock_registry = MagicMock()
        provider1 = MagicMock()
        provider2 = MagicMock()
        mock_registry.get_all_providers.return_value = [provider1, provider2]

        result = await strategy.select_provider(mock_registry)

        assert result is provider1

    @pytest.mark.asyncio
    async def test_should_fallback_returns_false_when_disabled(self) -> None:
        """Returns False when fallback is disabled in config."""
        strategy = DynamicFallbackStrategy()
        mock_provider = MagicMock()
        mock_provider.name = "test_provider"

        with patch.object(strategy, "_get_effective_provider_config") as mock_config:
            mock_fallback = MagicMock()
            mock_fallback.enabled = False
            mock_config.return_value = MagicMock(fallback=mock_fallback)

            result = await strategy.should_fallback(mock_provider, "error", None)

            assert result is False

    @pytest.mark.asyncio
    async def test_should_fallback_on_rate_limit_with_long_wait(self) -> None:
        """Falls back when rate limited with wait time exceeding threshold."""
        strategy = DynamicFallbackStrategy()
        mock_provider = MagicMock()
        mock_provider.name = "test_provider"

        with patch.object(strategy, "_get_effective_provider_config") as mock_config:
            mock_fallback = MagicMock()
            mock_fallback.enabled = True
            mock_fallback.rate_limit_wait_threshold_seconds = 30
            mock_config.return_value = MagicMock(fallback=mock_fallback)

            result = await strategy.should_fallback(mock_provider, "rate_limited", 60.0)

            assert result is True

    @pytest.mark.asyncio
    async def test_should_fallback_rate_limit_none_retry_after(self) -> None:
        """Returns False when rate limited but no retry_after provided."""
        strategy = DynamicFallbackStrategy()
        mock_provider = MagicMock()
        mock_provider.name = "test_provider"

        with patch.object(strategy, "_get_effective_provider_config") as mock_config:
            mock_fallback = MagicMock()
            mock_fallback.enabled = True
            mock_config.return_value = MagicMock(fallback=mock_fallback)

            result = await strategy.should_fallback(mock_provider, "rate_limited", None)

            assert result is False

    @pytest.mark.asyncio
    async def test_clear_provider_state_deletes_cache_key(self) -> None:
        """clear_provider_state deletes the fallback state cache key."""
        strategy = DynamicFallbackStrategy()

        with patch("ml_gateway_service.strategies.dynamic._cache") as mock_cache:
            mock_cache.delete = AsyncMock()

            await strategy.clear_provider_state("test_provider")

            mock_cache.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_provider_error_first_error(self) -> None:
        """Test _record_provider_error creates new state on first error."""
        from ml_gateway_service.strategies.dynamic import DynamicFallbackStrategy

        strategy = DynamicFallbackStrategy()

        with patch("ml_gateway_service.strategies.dynamic._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()

            consecutive, duration = await strategy._record_provider_error("test_provider")

            assert consecutive == 1
            assert duration >= 0
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_provider_error_increment(self) -> None:
        """Test _record_provider_error increments consecutive errors."""
        from ml_gateway_service.strategies.dynamic import DynamicFallbackStrategy

        strategy = DynamicFallbackStrategy()

        existing_state = {
            "first_error_at": 1000.0,
            "last_error_at": 1001.0,
            "consecutive_errors": 2,
        }

        with patch("ml_gateway_service.strategies.dynamic._cache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=existing_state)
            mock_cache.set = AsyncMock()

            consecutive, _ = await strategy._record_provider_error("test_provider")

            assert consecutive == 3
            mock_cache.set.assert_called_once()

    def test_get_effective_provider_config_from_settings(self) -> None:
        """Test _get_effective_provider_config returns config from settings."""
        from ml_gateway_service.strategies.dynamic import DynamicFallbackStrategy

        strategy = DynamicFallbackStrategy()
        mock_provider = MagicMock()
        mock_provider.name = "test_provider"

        mock_config = MagicMock()
        mock_config.name = "test_provider"

        with patch("ml_gateway_service.strategies.dynamic.settings") as mock_settings:
            mock_settings.provider_registry.providers = [mock_config]

            result = strategy._get_effective_provider_config(mock_provider)

            assert result is mock_config

    def test_get_effective_provider_config_defaults(self) -> None:
        """Test _get_effective_provider_config returns defaults when not in settings."""
        from ml_gateway_service.core.config import ProviderFallbackSettings
        from ml_gateway_service.strategies.dynamic import DynamicFallbackStrategy

        strategy = DynamicFallbackStrategy()
        mock_provider = MagicMock()
        mock_provider.name = "unknown_provider"
        mock_provider.default_enabled.return_value = True
        mock_provider.default_priority.return_value = 10
        mock_provider.default_fallback_settings.return_value = ProviderFallbackSettings(
            enabled=True,
            min_consecutive_errors=3,
            error_duration_threshold_seconds=60,
            rate_limit_wait_threshold_seconds=30,
        )

        with patch("ml_gateway_service.strategies.dynamic.settings") as mock_settings:
            mock_settings.provider_registry.providers = []

            result = strategy._get_effective_provider_config(mock_provider)

            assert result.name == "unknown_provider"
            assert result.enabled is True

    @pytest.mark.asyncio
    async def test_should_fallback_on_sustained_errors(self) -> None:
        """Test fallback triggered on sustained errors exceeding threshold."""
        from ml_gateway_service.strategies.dynamic import DynamicFallbackStrategy

        strategy = DynamicFallbackStrategy()
        mock_provider = MagicMock()
        mock_provider.name = "test_provider"

        existing_state = {
            "first_error_at": 1000.0,
            "last_error_at": 1005.0,
            "consecutive_errors": 5,
        }

        with (
            patch.object(strategy, "_get_effective_provider_config") as mock_config,
            patch("ml_gateway_service.strategies.dynamic._cache") as mock_cache,
        ):
            mock_fallback = MagicMock()
            mock_fallback.enabled = True
            mock_fallback.min_consecutive_errors = 3
            mock_fallback.error_duration_threshold_seconds = 4.0
            mock_config.return_value = MagicMock(fallback=mock_fallback)

            mock_cache.get = AsyncMock(return_value=existing_state)
            mock_cache.set = AsyncMock()

            result = await strategy.should_fallback(mock_provider, "some_error", None)

            assert result is True


class TestExplicitProviderStrategy:
    """Tests for ExplicitProviderStrategy."""

    @pytest.mark.asyncio
    async def test_returns_specified_provider(self) -> None:
        """Returns provider matching the explicit name."""
        strategy = ExplicitProviderStrategy("kubernetes")
        mock_registry = MagicMock()
        k8s_provider = MagicMock()
        k8s_provider.name = "kubernetes"
        mock_registry.get_enabled_provider.return_value = k8s_provider

        result = await strategy.select_provider(mock_registry)

        assert result is k8s_provider
        mock_registry.get_enabled_provider.assert_called_once_with("kubernetes")

    @pytest.mark.asyncio
    async def test_returns_none_when_provider_not_found(self) -> None:
        """Returns None when explicit provider not in registry."""
        strategy = ExplicitProviderStrategy("nonexistent")
        mock_registry = MagicMock()
        mock_registry.get_enabled_provider.return_value = None

        result = await strategy.select_provider(mock_registry)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_provider_name_configured(self) -> None:
        """Returns None when provider_name is not configured."""
        strategy = ExplicitProviderStrategy(None)
        strategy._provider_name = None
        mock_registry = MagicMock()

        result = await strategy.select_provider(mock_registry)

        assert result is None

    @pytest.mark.asyncio
    async def test_should_fallback_always_false(self) -> None:
        """Explicit strategy never falls back."""
        strategy = ExplicitProviderStrategy("kubernetes")
        mock_provider = MagicMock()

        result = await strategy.should_fallback(mock_provider, "error", None)

        assert result is False

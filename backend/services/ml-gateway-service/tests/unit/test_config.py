"""Unit tests for ml_gateway_service.core.config module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ml_gateway_service.core.config import (
    MLGatewayCachingSettings,
    MLKafkaSettings,
    ModalSettings,
    ProviderConfigSettings,
    ProviderFallbackSettings,
    ProviderRegistrySettings,
    Settings,
    get_manifest,
    get_settings,
)
from nohiki_ml_manifest import DEFAULT_MANIFEST_PATH
from pydantic import SecretStr


class TestProviderFallbackSettings:
    """Tests for ProviderFallbackSettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default fallback settings values."""
        fallback = ProviderFallbackSettings()

        assert fallback.enabled is True
        assert fallback.rate_limit_wait_threshold_seconds == 1800
        assert fallback.error_duration_threshold_seconds == 300
        assert fallback.min_consecutive_errors == 3


class TestProviderConfigSettings:
    """Tests for ProviderConfigSettings nested model."""

    def test_required_name(self) -> None:
        """Verifies name is required."""
        config = ProviderConfigSettings(name="test-provider")

        assert config.name == "test-provider"
        assert config.enabled is True
        assert config.priority == 100

    def test_custom_fallback(self) -> None:
        """Verifies custom fallback settings."""
        config = ProviderConfigSettings(
            name="test",
            fallback=ProviderFallbackSettings(enabled=False),
        )

        assert config.fallback.enabled is False


class TestProviderRegistrySettings:
    """Tests for ProviderRegistrySettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default registry settings."""
        registry = ProviderRegistrySettings()

        assert registry.providers == []
        assert registry.routing_strategy == "dynamic"
        assert registry.explicit_provider_name is None


class TestModalSettings:
    """Tests for ModalSettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default modal settings."""
        modal = ModalSettings()

        assert modal.token_id is None
        assert modal.token_secret is None
        assert modal.app_name == "nohiki-ml-encoding"

    def test_secret_str_values(self) -> None:
        """Verifies SecretStr handling."""
        modal = ModalSettings(
            token_id=SecretStr("id123"),
            token_secret=SecretStr("secret456"),
        )

        assert modal.token_id is not None
        assert modal.token_id.get_secret_value() == "id123"
        assert modal.token_secret is not None
        assert modal.token_secret.get_secret_value() == "secret456"


class TestMLKafkaSettings:
    """Tests for MLKafkaSettings extended model."""

    def test_default_values(self) -> None:
        """Verifies default ML Kafka consumer groups."""
        kafka = MLKafkaSettings()

        assert kafka.consumer_group_embedding == "ml-gateway-embedding-primary"
        assert kafka.consumer_group_rerank == "ml-gateway-rerank-primary"


class TestSettings:
    """Tests for Settings class with nested models."""

    def test_default_service_identity(self) -> None:
        """Verifies default service identity values."""
        settings = Settings()

        assert settings.service_name == "ml-gateway-service"
        assert settings.service_name_friendly == "ML Gateway Service"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False

    def test_nested_redis_settings(self) -> None:
        """Verifies nested redis settings via RedisMixin."""
        settings = Settings()

        assert "localhost" in str(settings.redis.dsn)
        # RedisMixin provides redis_url property
        assert settings.redis_url is not None
        assert "localhost" in settings.redis_url

    def test_nested_kafka_settings(self) -> None:
        """Verifies nested kafka settings with ML extensions."""
        settings = Settings()

        assert settings.kafka.bootstrap_servers == "localhost:29092"
        assert settings.kafka.consumer_group == "ml-gateway-service"
        assert settings.kafka.consumer_group_embedding == "ml-gateway-embedding-primary"
        assert settings.kafka.consumer_group_rerank == "ml-gateway-rerank-primary"

    def test_nested_provider_registry(self) -> None:
        """Verifies nested provider registry settings."""
        settings = Settings()

        assert settings.provider_registry.routing_strategy == "dynamic"
        assert settings.provider_registry.providers == []

    def test_nested_modal_settings(self) -> None:
        """Verifies nested modal settings."""
        settings = Settings()

        assert settings.modal.app_name == "nohiki-ml-encoding"
        assert settings.modal.token_id is None

    def test_observability_defaults(self) -> None:
        """Verifies observability settings defaults."""
        settings = Settings()

        assert settings.observability.logging.level == "INFO"
        assert settings.observability.otel_endpoint == ""


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Returns a Settings instance."""
        get_settings.cache_clear()

        # ML gateway has no database requirement
        settings = Settings()

        assert isinstance(settings, Settings)

    def test_caching_behavior(self) -> None:
        """Verifies get_settings returns cached instance."""
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2


class TestManifestPath:
    """Tests for manifest_path field and get_manifest function."""

    def test_default_manifest_path(self) -> None:
        """Verifies default manifest_path uses shared constant."""
        settings = Settings()
        assert settings.manifest_path == DEFAULT_MANIFEST_PATH

    def test_get_manifest_delegates_to_cache(self) -> None:
        """get_manifest delegates to ManifestCache.get with settings path."""
        with patch("ml_gateway_service.core.config.ManifestCache") as mock_cache:
            mock_cache.get.return_value = MagicMock()
            result = get_manifest()

        assert result is mock_cache.get.return_value
        mock_cache.get.assert_called_once()


class TestMLGatewayCachingSettings:
    """Tests for MLGatewayCachingSettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default caching settings values."""
        caching = MLGatewayCachingSettings()

        assert caching.provider_fallback_state_ttl_seconds == 86400

    def test_provider_configs(self) -> None:
        """Verifies external API provider configurations."""
        caching = MLGatewayCachingSettings()

        assert caching.qdrant_provider.name == "qdrant"
        assert caching.qdrant_provider.fallback_ttl_seconds == 86400

        assert caching.embedding_provider.name == "embedding"
        assert caching.embedding_provider.fallback_ttl_seconds == 86400

    def test_base_ttl_config_available(self) -> None:
        """Verifies base TTL config is available from CachingSettings."""
        caching = MLGatewayCachingSettings()

        assert caching.ttls.short == 300
        assert caching.ttls.medium == 3600
        assert caching.ttls.fallback_state == 86400

    def test_health_key_builders(self) -> None:
        """Verifies health key builder methods."""
        caching = MLGatewayCachingSettings()

        assert caching.qdrant_provider.health_key() == "api:qdrant:health"
        assert caching.embedding_provider.health_key() == "api:embedding:health"

    def test_settings_includes_caching(self) -> None:
        """Verifies Settings includes caching configuration."""
        settings = Settings()

        assert settings.caching is not None
        assert isinstance(settings.caching, MLGatewayCachingSettings)
        assert settings.caching.provider_fallback_state_ttl_seconds == 86400

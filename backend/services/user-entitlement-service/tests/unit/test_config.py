"""Unit tests for user_entitlement_service.core.config module."""

from __future__ import annotations

from user_entitlement_service.core.config import (
    Settings,
    get_settings,
)


class TestSettings:
    """Tests for Settings class with nested models."""

    def test_default_service_identity(self) -> None:
        """Verifies default service identity values."""
        settings = get_settings()

        assert settings.service_name == "user-entitlement-service"
        assert settings.service_name_friendly == "Entitlements Service"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False

    def test_nested_database_settings(self) -> None:
        """Verifies nested database settings from environment."""
        settings = get_settings()

        # DSN is set in conftest.py
        assert "localhost" in str(settings.database.dsn)
        assert "5432" in str(settings.database.dsn)

    def test_nested_kafka_settings(self) -> None:
        """Verifies nested kafka settings from environment."""
        settings = get_settings()

        # DSN is set in conftest.py
        assert "localhost:29092" in str(settings.kafka.dsn)
        assert settings.kafka.consumer_group == "default-group"

    def test_observability_defaults(self) -> None:
        """Verifies observability settings defaults."""
        settings = get_settings()

        assert settings.observability.logging.level == "INFO"
        assert settings.observability.otel_endpoint == ""


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Returns a Settings instance."""
        get_settings.cache_clear()
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_caching_behavior(self) -> None:
        """Verifies get_settings returns cached instance."""
        get_settings.cache_clear()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

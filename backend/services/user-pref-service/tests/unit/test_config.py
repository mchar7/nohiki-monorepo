"""Unit tests for user_pref_service.core.config module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from nohiki_db_utils import DatabaseSettings
from nohiki_db_utils.testing import TEST_DATABASE_DSN
from nohiki_kafka_client import KafkaSettings
from nohiki_ml_manifest.testing import get_test_manifest_path
from pydantic import PositiveInt, PostgresDsn
from user_pref_service.core.config import Settings, get_settings

TEST_DSN = PostgresDsn(TEST_DATABASE_DSN)


def _make_settings(
    database: DatabaseSettings | None = None,
    kafka: KafkaSettings | None = None,
    max_keywords: PositiveInt | int | None = None,
    max_locations: PositiveInt | int | None = None,
) -> Settings:
    """Create Settings with test defaults for testing."""
    return Settings(
        database=database or DatabaseSettings(dsn=TEST_DSN, schema_name="test_schema"),
        kafka=kafka or KafkaSettings(),
        max_keywords=50 if max_keywords is None else max_keywords,
        max_locations=20 if max_locations is None else max_locations,
    )


class TestSettings:
    """Tests for Settings class using mixins."""

    def test_default_service_identity(self) -> None:
        """Verifies default service identity values."""
        settings = _make_settings()

        assert settings.service_name == "user-pref-service"
        assert settings.service_name_friendly == "User Pref Service"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False

    def test_nested_database_settings(self) -> None:
        """Verifies nested database settings."""
        dsn = PostgresDsn("postgresql://myuser:secret@db.example.com:5433/mydb?sslmode=disable")
        settings = _make_settings(database=DatabaseSettings(dsn=dsn, schema_name="test_schema"))

        assert "db.example.com:5433" in settings.database.connection_string

    def test_nested_kafka_settings(self) -> None:
        """Verifies nested kafka settings defaults."""
        settings = _make_settings()

        assert settings.kafka.bootstrap_servers == "localhost:29092"
        assert settings.kafka.consumer_group == "default-group"

    def test_profile_limits_defaults(self) -> None:
        """Verifies profile limits settings defaults."""
        settings = _make_settings()

        assert settings.max_keywords == 50
        assert settings.max_locations == 20

    def test_profile_limits_custom(self) -> None:
        """Verifies profile limits can be customized."""
        settings = _make_settings(max_keywords=100, max_locations=30)

        assert settings.max_keywords == 100
        assert settings.max_locations == 30

    def test_profile_limits_must_be_positive(self) -> None:
        """Verifies limits must be positive integers."""
        with pytest.raises(ValueError, match=r"greater than 0"):
            _make_settings(max_keywords=0)

    def test_observability_defaults(self) -> None:
        """Verifies observability settings defaults."""
        settings = _make_settings()

        assert settings.observability.logging.level == "INFO"
        assert settings.observability.otel_endpoint == ""


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Returns a Settings instance."""
        settings = _make_settings()
        assert isinstance(settings, Settings)

    def test_caching_behavior(self) -> None:
        """Verifies get_settings returns cached instance."""
        get_settings.cache_clear()

        env_vars = {
            "USER_PREF_DATABASE__DSN": TEST_DATABASE_DSN,
            "USER_PREF_DATABASE__SCHEMA_NAME": "test_schema",
            "USER_PREF_KAFKA__DSN": "kafka://localhost:29092",
            "USER_PREF_MANIFEST_PATH": str(get_test_manifest_path()),
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

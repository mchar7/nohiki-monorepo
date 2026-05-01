"""Unit tests for user_upload_service.core.config module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from user_upload_service.core.config import (
    Settings,
    UploadSettings,
    get_settings,
)


def _test_env_vars() -> dict[str, str]:
    """Return environment variables for test Settings instantiation."""
    return {
        "USER_UPLOAD_DATABASE__DSN": "postgresql://test:pass@localhost:5432/test_db",
        "USER_UPLOAD_KAFKA__BOOTSTRAP_SERVERS": "localhost:29092",
        "USER_UPLOAD_KAFKA__CONSUMER_GROUP": "default-group",
        "USER_UPLOAD_S3__ENDPOINT": "http://localhost:9000",
        "USER_UPLOAD_S3__ACCESS_KEY": "minioadmin",
        "USER_UPLOAD_S3__SECRET_KEY": "minioadmin",
        "USER_UPLOAD_S3__BUCKET": "test-bucket",
    }


def _create_settings(**overrides: str) -> Settings:
    """Create Settings with test environment variables."""
    env_vars = _test_env_vars()
    env_vars.update(overrides)
    with patch.dict(os.environ, env_vars, clear=False):
        return Settings()


class TestUploadSettings:
    """Tests for UploadSettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default upload settings values."""
        upload = UploadSettings()

        assert upload.max_size_mb == 10

    def test_max_size_bytes_property(self) -> None:
        """Verifies max_size_bytes calculation."""
        upload = UploadSettings(max_size_mb=10)

        assert upload.max_size_bytes == 10 * 1024 * 1024

    def test_max_size_bytes_custom(self) -> None:
        """Verifies max_size_bytes with custom MB value."""
        upload = UploadSettings(max_size_mb=50)

        assert upload.max_size_bytes == 50 * 1024 * 1024

    def test_must_be_positive(self) -> None:
        """Verifies max_size_mb must be positive integer."""
        with pytest.raises(ValueError, match=r"greater than 0"):
            UploadSettings(max_size_mb=0)


class TestSettings:
    """Tests for Settings class with nested models."""

    def test_default_service_identity(self) -> None:
        """Verifies default service identity values."""
        settings = _create_settings()

        assert settings.service_name == "user-upload-service"
        assert settings.service_name_friendly == "Upload Service"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False

    def test_nested_database_settings(self) -> None:
        """Verifies nested database settings access."""
        settings = _create_settings(USER_UPLOAD_DATABASE__DSN="postgresql://myuser:secret@db.example.com:5433/mydb")

        assert "db.example.com:5433" in settings.database.connection_string
        assert "mydb" in settings.database.connection_string

    def test_nested_kafka_settings(self) -> None:
        """Verifies nested kafka settings defaults."""
        settings = _create_settings()

        assert settings.kafka.bootstrap_servers == "localhost:29092"
        assert settings.kafka.consumer_group == "default-group"

    def test_nested_upload_settings(self) -> None:
        """Verifies nested upload settings."""
        settings = _create_settings()

        assert settings.upload.max_size_mb == 10
        assert settings.upload.max_size_bytes == 10 * 1024 * 1024

    def test_observability_defaults(self) -> None:
        """Verifies observability settings defaults."""
        settings = _create_settings()

        assert settings.observability.logging.level == "INFO"
        assert settings.observability.otel_endpoint == ""


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Returns a Settings instance."""
        get_settings.cache_clear()

        settings = _create_settings()

        assert isinstance(settings, Settings)

    def test_caching_behavior(self) -> None:
        """Verifies get_settings returns cached instance."""
        get_settings.cache_clear()

        env_vars = _test_env_vars()

        with patch.dict(os.environ, env_vars, clear=False):
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

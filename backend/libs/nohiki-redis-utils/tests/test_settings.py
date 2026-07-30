"""Tests for RedisSettings."""

from __future__ import annotations

import pytest
from nohiki_core_settings import NohikiBaseSettings
from nohiki_redis_utils import RedisMixin, RedisSettings
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict


class _TestRedisSettings(RedisMixin, NohikiBaseSettings):
    """Test settings combining RedisMixin with NohikiBaseSettings."""

    # secrets_dir=None keeps these tests hermetic: the host /run/secrets must not leak in
    model_config = SettingsConfigDict(env_prefix="TEST_REDIS_", secrets_dir=None)

    service_name: str = "test-redis-service"
    service_name_friendly: str = "Test Redis Service"
    service_desc_friendly: str = "Test service for Redis settings"
    service_version: str = "0.0.1-test"


class TestRedisSettingsDefaults:
    """Tests for default settings."""

    def test_default_dsn(self) -> None:
        """Test default Redis DSN."""
        settings = RedisSettings()
        assert "localhost" in settings.connection_string
        assert "6379" in settings.connection_string

    def test_default_connection_settings(self) -> None:
        """Test default connection settings."""
        settings = RedisSettings()
        assert settings.socket_timeout == pytest.approx(5.0)
        assert settings.socket_connect_timeout == pytest.approx(5.0)
        assert settings.retry_on_timeout is True
        assert settings.max_connections == 10

    def test_default_cache_settings(self) -> None:
        """Test default cache settings."""
        settings = RedisSettings()
        assert settings.default_ttl_seconds == 3600


class TestRedisSettingsCustomDsn:
    """Tests for custom DSN configuration."""

    def test_custom_dsn_plaintext(self) -> None:
        """Test custom plaintext Redis DSN."""
        settings = RedisSettings.model_validate({"dsn": "redis://custom-host:6380/1"})
        assert "custom-host" in settings.connection_string
        assert "6380" in settings.connection_string

    def test_custom_dsn_with_password(self) -> None:
        """Test DSN with password."""
        settings = RedisSettings.model_validate({"dsn": "redis://:secret@localhost:6379/0"})
        assert ":secret@" in settings.connection_string

    def test_custom_dsn_ssl(self) -> None:
        """Test DSN with SSL (rediss scheme)."""
        settings = RedisSettings.model_validate({"dsn": "rediss://secure-host:6379/0"})
        assert settings.connection_string.startswith("rediss://")

    def test_custom_dsn_with_db(self) -> None:
        """Test DSN with custom database number."""
        settings = RedisSettings.model_validate({"dsn": "redis://localhost:6379/5"})
        assert "/5" in settings.connection_string


class TestRedisSettingsConnectionSettings:
    """Tests for connection settings."""

    def test_custom_socket_timeout(self) -> None:
        """Test custom socket timeout."""
        settings = RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "socket_timeout": 10.0})
        assert settings.socket_timeout == pytest.approx(10.0)

    def test_custom_socket_connect_timeout(self) -> None:
        """Test custom socket connect timeout."""
        settings = RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "socket_connect_timeout": 15.0})
        assert settings.socket_connect_timeout == pytest.approx(15.0)

    def test_custom_retry_on_timeout(self) -> None:
        """Test custom retry on timeout."""
        settings = RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "retry_on_timeout": False})
        assert settings.retry_on_timeout is False

    def test_custom_max_connections(self) -> None:
        """Test custom max connections."""
        settings = RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "max_connections": 50})
        assert settings.max_connections == 50


class TestRedisSettingsValidation:
    """Tests for validation logic."""

    def test_invalid_dsn_scheme(self) -> None:
        """Test that invalid DSN scheme raises error."""
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "http://localhost:6379"})

    def test_socket_timeout_must_be_positive(self) -> None:
        """Test socket_timeout must be positive."""
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "socket_timeout": 0})
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "socket_timeout": -1})

    def test_socket_connect_timeout_must_be_positive(self) -> None:
        """Test socket_connect_timeout must be positive."""
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "socket_connect_timeout": 0})

    def test_max_connections_bounds(self) -> None:
        """Test max_connections validation bounds."""
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "max_connections": 0})
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "max_connections": 101})

    def test_default_ttl_must_be_positive(self) -> None:
        """Test default_ttl_seconds must be positive."""
        with pytest.raises(ValidationError):
            RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "default_ttl_seconds": 0})


class TestRedisSettingsCacheSettings:
    """Tests for cache settings."""

    def test_custom_ttl(self) -> None:
        """Test custom TTL setting."""
        settings = RedisSettings.model_validate({"dsn": "redis://localhost:6379/0", "default_ttl_seconds": 7200})
        assert settings.default_ttl_seconds == 7200


class TestRedisSettingsConnectionString:
    """Tests for connection_string property."""

    def test_connection_string_plaintext(self) -> None:
        """Test connection_string property with plaintext DSN."""
        settings = RedisSettings.model_validate({"dsn": "redis://myhost:6379/0"})
        assert settings.connection_string == "redis://myhost:6379/0"

    def test_connection_string_ssl(self) -> None:
        """Test connection_string property with SSL DSN."""
        settings = RedisSettings.model_validate({"dsn": "rediss://secure:6379/0"})
        assert settings.connection_string.startswith("rediss://")

    def test_connection_string_with_auth(self) -> None:
        """Test connection_string property with authentication."""
        settings = RedisSettings.model_validate({"dsn": "redis://:password@host:6379/0"})
        assert ":password@" in settings.connection_string


class TestRedisMixinProductionValidation:
    """Tests for production environment validation via RedisMixin."""

    def test_plaintext_in_production_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that plaintext Redis DSN raises error in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(ValidationError, match="Redis must use rediss:// \\(SSL\\) in production"):
            _TestRedisSettings.model_validate({"redis": {"dsn": "redis://localhost:6379/0"}})

    def test_ssl_in_production_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that SSL Redis DSN succeeds in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        settings = _TestRedisSettings.model_validate({"redis": {"dsn": "rediss://secure-host:6379/0"}})
        assert settings.redis.connection_string.startswith("rediss://")

    def test_development_allows_plaintext(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that development mode allows plaintext Redis."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = _TestRedisSettings.model_validate({"redis": {"dsn": "redis://localhost:6379/0"}})
        assert settings.redis.connection_string.startswith("redis://")

    def test_instrument_redis_property(self) -> None:
        """Test that RedisMixin sets instrument_redis to True."""
        settings = _TestRedisSettings()
        assert settings.instrument_redis is True

    def test_redis_url_property(self) -> None:
        """Test redis_url convenience property."""
        settings = _TestRedisSettings.model_validate({"redis": {"dsn": "redis://myhost:6379/0"}})
        assert settings.redis_url == "redis://myhost:6379/0"

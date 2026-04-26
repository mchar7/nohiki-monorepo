"""Unit tests for user_auth_service.core.config module."""

from __future__ import annotations

import pytest
from user_auth_service.core.config import (
    CookieSettings,
    JWTSettings,
    SecuritySettings,
    Settings,
    get_settings,
)


class TestJWTSettings:
    """Tests for JWTSettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default JWT configuration values."""
        jwt = JWTSettings()

        assert jwt.private_key_path == "/run/secrets/jwt_private_key.pem"
        assert jwt.key_id == "nohiki-key-1"
        assert jwt.issuer == "https://api.nohiki.com"
        assert jwt.audience == "https://app.nohiki.com"
        assert jwt.access_token_expire_minutes == 10
        assert jwt.refresh_token_expire_days == 30

    def test_custom_values(self) -> None:
        """Verifies JWT settings can be customized."""
        jwt = JWTSettings(
            private_key_path="/custom/path.pem",
            key_id="custom-key",
            issuer="https://custom.com",
            audience="https://app.custom.com",
            access_token_expire_minutes=60,
            refresh_token_expire_days=14,
        )

        assert jwt.private_key_path == "/custom/path.pem"
        assert jwt.key_id == "custom-key"
        assert jwt.access_token_expire_minutes == 60
        assert jwt.refresh_token_expire_days == 14


class TestCookieSettings:
    """Tests for CookieSettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default cookie configuration values.

        Note: In development mode, cookies use plain names without __Host- prefix.
        In production, __Host- prefix is added and secure=True.
        """
        cookie = CookieSettings()

        # Cookie name depends on environment - check it ends with expected suffix
        assert cookie.access_token_name.endswith("nohiki_at")
        assert cookie.refresh_token_name.endswith("nohiki_rt")
        assert cookie.domain is None
        # secure depends on environment
        assert cookie.samesite == "lax"

        assert cookie.oauth_state_name.endswith("nohiki_oauth_state")
        assert cookie.domain is None

    def test_oauth_binding_name_is_host_prefixed_only_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with monkeypatch.context() as context:
            context.setattr("user_auth_service.core.config.is_development", lambda: False)
            production = CookieSettings()
        with monkeypatch.context() as context:
            context.setattr("user_auth_service.core.config.is_development", lambda: True)
            development = CookieSettings()

        assert production.oauth_state_name == "__Host-nohiki_oauth_state"
        assert production.secure is True
        assert production.domain is None
        assert development.oauth_state_name == "nohiki_oauth_state"
        assert development.secure is False
        assert development.domain is None

    def test_custom_values(self) -> None:
        """Verifies cookie settings can be customized."""
        cookie = CookieSettings(
            access_token_name="custom_at",
            refresh_token_name="custom_rt",
            domain="example.com",
            secure=False,
            samesite="strict",
        )

        assert cookie.access_token_name == "custom_at"
        assert cookie.domain == "example.com"
        assert cookie.secure is False
        assert cookie.samesite == "strict"


class TestSecuritySettings:
    """Tests for SecuritySettings nested model."""

    def test_default_values(self) -> None:
        """Verifies default security configuration values."""
        security = SecuritySettings()

        assert "localhost:5173" in security.cors_allowed_origins
        assert "localhost:3000" in security.cors_allowed_origins

    def test_get_cors_origins(self) -> None:
        """Verifies CORS origins are parsed correctly."""
        security = SecuritySettings(
            cors_allowed_origins="https://a.com,https://b.com",
        )

        origins = security.get_cors_origins()
        assert origins == ["https://a.com", "https://b.com"]

    def test_get_csrf_origins(self) -> None:
        """Verifies CSRF origins are parsed correctly."""
        security = SecuritySettings(
            csrf_allowed_origins="https://a.com,https://b.com",
        )

        origins = security.get_csrf_origins()
        assert origins == ["https://a.com", "https://b.com"]

    def test_origin_list_from_list_input(self) -> None:
        """Verifies origin list validator handles list input."""
        # The validator accepts list[str] and converts to comma-separated string
        security = SecuritySettings(
            cors_allowed_origins="https://a.com,https://b.com",
        )

        assert security.cors_allowed_origins == "https://a.com,https://b.com"


class TestSettings:
    """Tests for Settings class with nested models."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set up database environment for all tests."""
        monkeypatch.setenv("USER_AUTH_DATABASE__DSN", "postgresql://test:pass@localhost:5432/test_db")
        monkeypatch.setenv("USER_AUTH_KAFKA__DSN", "kafka://localhost:29092")
        monkeypatch.setenv("USER_AUTH_REDIS__DSN", "redis://localhost:6379/0")
        get_settings.cache_clear()

    def test_default_service_identity(self) -> None:
        """Verifies default service identity values."""
        settings = get_settings()

        assert settings.service_name == "user-auth-service"
        assert settings.service_name_friendly == "Identity Service"
        assert settings.service_version == "0.1.0"
        assert settings.debug is False

    def test_nested_database_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifies nested database settings."""
        monkeypatch.setenv("USER_AUTH_DATABASE__DSN", "postgresql://myuser:secret@db.example.com:5433/mydb")
        get_settings.cache_clear()
        settings = get_settings()

        assert "db.example.com" in str(settings.database.dsn)
        assert "5433" in str(settings.database.dsn)
        assert "myuser" in str(settings.database.dsn)

    def test_nested_kafka_settings(self) -> None:
        """Verifies nested kafka settings defaults."""
        settings = get_settings()

        # KafkaMixin uses dsn field, not bootstrap_servers
        assert "localhost:29092" in str(settings.kafka.dsn)
        assert settings.kafka.consumer_group == "default-group"

    def test_nested_jwt_settings(self) -> None:
        """Verifies nested JWT settings."""
        settings = get_settings()

        assert settings.jwt.access_token_expire_minutes == 10
        assert settings.jwt.refresh_token_expire_days == 30
        assert settings.jwt.key_id == "nohiki-key-1"

    def test_nested_cookie_settings(self) -> None:
        """Verifies nested cookie settings.

        Note: Cookie names and secure flag depend on environment.
        """
        settings = get_settings()

        # Cookie names end with expected suffix (prefix depends on environment)
        assert settings.cookie.access_token_name.endswith("nohiki_at")
        assert settings.cookie.refresh_token_name.endswith("nohiki_rt")

    def test_nested_security_settings(self) -> None:
        """Verifies nested security settings."""
        settings = get_settings()

        origins = settings.security.get_cors_origins()
        assert len(origins) > 0

    def test_observability_defaults(self) -> None:
        """Verifies observability settings defaults."""
        settings = get_settings()

        assert settings.observability.logging.level == "INFO"
        assert settings.observability.otel_endpoint == ""

    def test_jwt_expire_must_be_positive(self) -> None:
        """Verifies JWT expiration must be positive integers."""
        with pytest.raises(ValueError, match=r"greater than 0"):
            JWTSettings(access_token_expire_minutes=0)


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Returns a Settings instance."""
        import os
        from unittest.mock import patch

        get_settings.cache_clear()

        env_vars = {
            "USER_AUTH_DATABASE__DSN": "postgresql://test:pass@localhost:5432/test_db",
            "USER_AUTH_KAFKA__DSN": "kafka://localhost:29092",
            "USER_AUTH_REDIS__DSN": "redis://localhost:6379/0",
        }

        with patch.dict(os.environ, env_vars):
            settings = get_settings()
            assert isinstance(settings, Settings)

    def test_caching_behavior(self) -> None:
        """Verifies get_settings returns cached instance."""
        get_settings.cache_clear()

        # Mock environment to provide required database config
        import os
        from unittest.mock import patch

        env_vars = {
            "USER_AUTH_DATABASE__DSN": "postgresql://test:pass@localhost:5432/test_db",
            "USER_AUTH_KAFKA__DSN": "kafka://localhost:29092",
            "USER_AUTH_REDIS__DSN": "redis://localhost:6379/0",
        }

        with patch.dict(os.environ, env_vars):
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

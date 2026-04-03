"""Tests for DatabaseSettings."""

from __future__ import annotations

import ssl

import pytest
from nohiki_db_utils import DatabaseSettings
from pydantic import ValidationError


class TestDatabaseSettingsDsnMode:
    """Tests for DSN mode configuration."""

    def test_dsn_mode_basic(self) -> None:
        """Test configuration via complete DSN."""
        settings = DatabaseSettings(
            dsn="postgresql://user:pass@localhost:5432/mydb",
            schema_name="test_schema",
        )
        assert "postgresql+asyncpg://user:pass@localhost:5432/mydb" in settings.connection_string

    def test_dsn_mode_already_async(self) -> None:
        """Test DSN that already has asyncpg driver."""
        settings = DatabaseSettings(
            dsn="postgresql+asyncpg://user:pass@localhost:5432/mydb",
            schema_name="test_schema",
        )
        assert settings.connection_string == "postgresql+asyncpg://user:pass@localhost:5432/mydb"

    def test_dsn_mode_with_query_params(self) -> None:
        """Test DSN with query parameters - sslmode is stripped for asyncpg (handled via connect_args)."""
        settings = DatabaseSettings(
            dsn="postgresql://user:pass@localhost:5432/mydb?sslmode=require",
            schema_name="test_schema",
        )
        # sslmode is stripped from async URL - asyncpg uses ssl connect_arg instead
        assert "sslmode" not in settings.connection_string
        # But it's preserved in the original DSN and used for connect_args
        connect_args = settings.get_connect_args()
        assert "ssl" in connect_args

    def test_sync_connection_string_from_dsn(self) -> None:
        """Test sync connection string uses psycopg driver."""
        settings = DatabaseSettings(
            dsn="postgresql://user:pass@localhost/db",
            schema_name="test_schema",
        )
        sync_str = settings.sync_connection_string
        assert "+asyncpg" not in sync_str
        assert "postgresql+psycopg://" in sync_str


class TestDatabaseSettingsDsnWithCredentials:
    """Tests for DSN with embedded credentials."""

    def test_dsn_with_credentials(self) -> None:
        """Test DSN with embedded user and password."""
        settings = DatabaseSettings(
            dsn="postgresql://myuser:secret@db.example.com:5433/mydb",
            schema_name="test_schema",
        )
        assert "db.example.com:5433" in settings.connection_string
        assert "myuser:secret@" in settings.connection_string
        assert "mydb" in settings.connection_string

    def test_dsn_without_password(self) -> None:
        """Test DSN without password."""
        settings = DatabaseSettings(
            dsn="postgresql://postgres@localhost:5432/test",
            schema_name="test_schema",
        )
        conn_str = settings.connection_string
        assert "postgres@localhost" in conn_str

    def test_dsn_with_default_port(self) -> None:
        """Test DSN with default port."""
        settings = DatabaseSettings(
            dsn="postgresql://postgres@localhost:5432/test",
            schema_name="test_schema",
        )
        assert ":5432/" in settings.connection_string

    def test_dsn_ssl_mode_via_connect_args(self) -> None:
        """Test SSL mode is extracted from DSN and used in connect_args."""
        settings = DatabaseSettings(
            dsn="postgresql://postgres@localhost/test?sslmode=require",
            schema_name="test_schema",
        )
        # SSL mode is configured via connect_args, not in the URL
        connect_args = settings.get_connect_args()
        assert "ssl" in connect_args


class TestDatabaseSettingsValidation:
    """Tests for validation logic."""

    def test_requires_dsn(self) -> None:
        """Test that DSN is required."""
        with pytest.raises(ValidationError):
            DatabaseSettings()

    def test_invalid_dsn_scheme(self) -> None:
        """Test that invalid DSN scheme raises error."""
        with pytest.raises(ValidationError):
            DatabaseSettings(dsn="mysql://localhost/db")

    def test_invalid_dsn_format(self) -> None:
        """Test that invalid DSN format raises error."""
        with pytest.raises(ValidationError):
            DatabaseSettings(dsn="not-a-valid-dsn")


class TestDatabaseSettingsPoolSettings:
    """Tests for connection pool settings."""

    def test_pool_settings_defaults(self) -> None:
        """Test default pool settings."""
        settings = DatabaseSettings(dsn="postgresql://localhost/db", schema_name="test_schema")
        assert settings.pool_size == 5
        assert settings.max_overflow == 10
        assert settings.pool_timeout == 30
        assert settings.pool_recycle == 1800

    def test_pool_settings_custom(self) -> None:
        """Test custom pool settings."""
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db",
            schema_name="test_schema",
            pool_size=10,
            max_overflow=20,
            pool_timeout=60,
            pool_recycle=3600,
        )
        assert settings.pool_size == 10
        assert settings.max_overflow == 20
        assert settings.pool_timeout == 60
        assert settings.pool_recycle == 3600

    def test_pool_size_bounds(self) -> None:
        """Test pool_size validation bounds."""
        with pytest.raises(ValidationError):
            DatabaseSettings(dsn="postgresql://localhost/db", schema_name="test_schema", pool_size=0)
        with pytest.raises(ValidationError):
            DatabaseSettings(
                dsn="postgresql://localhost/db",
                schema_name="test_schema",
                pool_size=100,
            )


class TestDatabaseSettingsMigration:
    """Tests for migration settings."""

    def test_migration_defaults(self) -> None:
        """Test default migration settings - defaults to True in development."""
        settings = DatabaseSettings(dsn="postgresql://localhost/db", schema_name="test_schema")
        assert settings.migrate_on_startup is True
        assert settings.migration_timeout_seconds == 900

    def test_migration_custom(self) -> None:
        """Test custom migration settings."""
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db",
            schema_name="test_schema",
            migrate_on_startup=True,
            migration_timeout_seconds=1200,
        )
        assert settings.migrate_on_startup is True
        assert settings.migration_timeout_seconds == 1200

    def test_migration_timeout_bounds(self) -> None:
        """Test migration timeout validation."""
        with pytest.raises(ValidationError):
            DatabaseSettings(
                dsn="postgresql://localhost/db",
                schema_name="test_schema",
                migration_timeout_seconds=30,
            )


class TestDatabaseSettingsSSL:
    """Tests for SSL configuration."""

    def test_get_connect_args_disable_in_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslmode=disable returns empty connect_args in development."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=disable",
            schema_name="test_schema",
        )
        connect_args = settings.get_connect_args()
        assert connect_args == {}

    def test_get_connect_args_disable_in_prod_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslmode=disable raises error in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=disable",
            schema_name="test_schema",
        )
        with pytest.raises(ValueError, match="sslmode=disable is not allowed in production"):
            settings.get_connect_args()

    def test_get_connect_args_prefer_in_prod_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslmode=prefer raises error in production."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=prefer",
            schema_name="test_schema",
        )
        with pytest.raises(ValueError, match="sslmode=prefer is not allowed in production"):
            settings.get_connect_args()

    def test_get_connect_args_require_returns_ssl_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslmode=require returns SSL context."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=require",
            schema_name="test_schema",
        )
        connect_args = settings.get_connect_args()
        assert "ssl" in connect_args
        ctx = connect_args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False

    def test_get_connect_args_verify_full_checks_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslmode=verify-full enables hostname checking."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=verify-full",
            schema_name="test_schema",
        )
        connect_args = settings.get_connect_args()
        ctx = connect_args["ssl"]
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_get_connect_args_verify_ca_requires_cert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sslmode=verify-ca requires certificate verification."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=verify-ca",
            schema_name="test_schema",
        )
        connect_args = settings.get_connect_args()
        ctx = connect_args["ssl"]
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is False

    def test_get_connect_args_default_sslmode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default sslmode is require when not specified."""
        monkeypatch.setenv("ENVIRONMENT", "development")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db",
            schema_name="test_schema",
        )
        connect_args = settings.get_connect_args()
        assert "ssl" in connect_args

    def test_get_connect_args_production_enforces_cert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test production enforces certificate verification even with require."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=require",
            schema_name="test_schema",
        )
        connect_args = settings.get_connect_args()
        ctx = connect_args["ssl"]
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_get_ssl_mode_extracts_from_dsn(self) -> None:
        """Test _get_ssl_mode extracts sslmode from DSN."""
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=verify-full&application_name=test",
            schema_name="test_schema",
        )
        assert settings._get_ssl_mode() == "verify-full"

    def test_get_async_url_preserves_other_params(self) -> None:
        """Test get_async_url preserves non-sslmode query params."""
        settings = DatabaseSettings(
            dsn="postgresql://localhost/db?sslmode=require&application_name=myapp",
            schema_name="test_schema",
        )
        url = settings.get_async_url()
        url_str = url.render_as_string(hide_password=False)
        assert "application_name=myapp" in url_str
        assert "sslmode" not in url_str

"""Database configuration settings and mixin for Nohiki services."""

from __future__ import annotations

import ssl
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from nohiki_core_settings import SettingsMixin
from nohiki_core_settings.env import is_development
from pydantic import BaseModel, Field, PostgresDsn

if TYPE_CHECKING:
    from sqlalchemy.engine import URL

type MakeUrlType = Callable[[str], "URL"]

_SQLALCHEMY_AVAILABLE = False
_make_url: MakeUrlType | None = None

try:
    from sqlalchemy.engine import make_url

    _SQLALCHEMY_AVAILABLE = True
    _make_url = cast("MakeUrlType", make_url)
except ImportError:
    pass


def _default_migrate_on_startup() -> bool:
    """Create factory for dynamic migrate_on_startup field default."""
    return is_development()


class DatabaseSettings(BaseModel):
    """Database settings: requires sqlalchemy to be installed."""

    def __init__(self, **data: object) -> None:
        """Initialize settings, verifying SQLAlchemy is available.

        Raises:
            ImportError: If sqlalchemy is not installed.

        """
        if not _SQLALCHEMY_AVAILABLE:
            msg = "DatabaseSettings requires SQLAlchemy. Install nohiki-db-utils with database support."
            raise ImportError(msg)
        super().__init__(**data)

    dsn: PostgresDsn = Field(description="PostgreSQL connection string")
    schema_name: str = Field(description="Service-specific PostgreSQL schema name for tables and outbox")

    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout: int = Field(default=30, ge=1)
    pool_recycle: int = Field(default=1800, ge=60)

    migrate_on_startup: bool = Field(default_factory=_default_migrate_on_startup)
    migration_timeout_seconds: int = Field(default=900, ge=60)

    def _get_ssl_mode(self) -> str:
        """Extract sslmode from DSN query params."""
        parsed = urlparse(str(self.dsn))
        params = parse_qs(parsed.query)
        return params.get("sslmode", ["require"])[0]

    def _get_base_url(self) -> URL:
        """Get base SQLAlchemy URL from DSN."""
        if _make_url is None:
            msg = "SQLAlchemy is required for URL generation."
            raise ImportError(msg)
        return _make_url(str(self.dsn))

    def get_async_url(self) -> URL:
        """Get SQLAlchemy URL configured for asyncpg driver."""
        parsed = urlparse(str(self.dsn))
        params = parse_qs(parsed.query)
        params.pop("sslmode", None)
        clean_query = urlencode({k: v[0] for k, v in params.items()}) if params else ""
        clean_url = urlunparse(parsed._replace(query=clean_query))
        if _make_url is None:
            msg = "SQLAlchemy is required for URL generation."
            raise ImportError(msg)
        return _make_url(clean_url).set(drivername="postgresql+asyncpg")

    def get_sync_url(self) -> URL:
        """Get SQLAlchemy URL configured for psycopg (sync) driver."""
        return self._get_base_url().set(drivername="postgresql+psycopg")

    @property
    def connection_string(self) -> str:
        """Get async connection string for service code."""
        return self.get_async_url().render_as_string(hide_password=False)

    @property
    def sync_connection_string(self) -> str:
        """Get sync connection string for Alembic migrations."""
        return self.get_sync_url().render_as_string(hide_password=False)

    def get_connect_args(self) -> dict[str, Any]:
        """Get connect_args for SQLAlchemy async engine (SSL handling for asyncpg)."""
        ssl_mode = self._get_ssl_mode()

        if ssl_mode in ("disable", "prefer") and not is_development():
            msg = f"sslmode={ssl_mode} is not allowed in production. Use require/verify-ca/verify-full."
            raise ValueError(msg)

        if ssl_mode == "disable":
            return {}

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = ssl_mode == "verify-full"
        ctx.verify_mode = (
            ssl.CERT_REQUIRED if ssl_mode in ("verify-ca", "verify-full") or not is_development() else ssl.CERT_NONE
        )
        return {"ssl": ctx}


class DatabaseMixin(SettingsMixin):
    """Mixin that declares database as required. Combine with NohikiBaseSettings.

    Usage::

        class Settings(DatabaseMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
    """

    database: DatabaseSettings

    @property
    def database_url(self) -> str:
        """Get database connection string."""
        return self.database.connection_string

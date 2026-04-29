"""PostgreSQL integration fixtures for user-pref-service."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from nohiki_db_utils.testing import (
    async_engine,
    async_session,
    async_session_factory,
    postgres_container,
)

__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "postgres_container",
]

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def setup_database_schema(postgres_container: str) -> None:
    """Apply the service's real migrations to the integration database."""
    sync_url = postgres_container.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    config = Config(str(_SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    config.set_main_option("path_separator", "os")
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url

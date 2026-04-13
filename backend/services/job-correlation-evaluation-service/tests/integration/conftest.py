"""Integration test fixtures requiring Docker/testcontainers."""

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from nohiki_db_utils.testing import (
    get_async_engine,
    get_async_sessionmaker,
    postgres_container,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "postgres_container",
]


_SERVICE_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def async_engine(
    postgres_container: str,
) -> AsyncGenerator[AsyncEngine]:
    """Create an async engine compatible with pytest-asyncio strict mode."""
    engine = get_async_engine(postgres_container)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def async_session_factory(
    async_engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """Create a session factory compatible with strict async fixtures."""
    yield get_async_sessionmaker(async_engine)


@pytest_asyncio.fixture
async def async_session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Provide a real PostgreSQL session for one test."""
    async with async_session_factory() as session:
        yield session


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

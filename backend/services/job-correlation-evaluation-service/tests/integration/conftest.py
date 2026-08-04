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
from nohiki_redis_utils import RedisCache
from nohiki_redis_utils.testing import redis_container
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "postgres_container",
    "redis_cache",
    "redis_container",
    "setup_database_schema",
]


_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_TRUNCATE_TABLES = (
    "job_correlation_schema.correlations",
    "job_correlation_schema.profile_projections",
    "job_correlation_schema.processed_events",
    "feedback.asymmetric_feedback",
    "feedback.manual_adjustments",
)


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
    async_engine: AsyncEngine,
    async_session_factory: async_sessionmaker[AsyncSession],
    setup_database_schema: None,
) -> AsyncGenerator[AsyncSession]:
    """Provide an isolated real PostgreSQL session for one test."""
    _ = setup_database_schema
    async with async_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {', '.join(_TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"))

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


@pytest_asyncio.fixture
async def redis_cache(redis_container: str) -> AsyncGenerator[RedisCache]:
    """Provide an isolated real Redis cache for one test."""
    cache = RedisCache(redis_url=redis_container, service_name="test")
    await cache.delete("active_profiles")
    try:
        yield cache
    finally:
        await cache.delete("active_profiles")
        await cache.close()

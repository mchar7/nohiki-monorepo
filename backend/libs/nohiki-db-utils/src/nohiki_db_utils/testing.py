"""Testing utilities for database - testcontainer fixtures and helpers.

Provides:
    - ``create_mock_session``: Lightweight mock for unit tests (no Docker required).
    - ``postgres_container`` / ``async_session``: Real PostgreSQL fixtures for integration tests.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

import pytest
from nohiki_test_utils import docker_daemon_available
from pytest_unused_fixtures import ignore_unused_fixture
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def create_mock_session() -> MagicMock:
    """Create a properly spec'd mock for SQLAlchemy AsyncSession.

    Returns ``MagicMock(spec=AsyncSession)`` which auto-detects sync vs async methods:
    sync calls (``add``, ``add_all``, ``expunge``, ``expunge_all``, ``is_modified``,
    ``get_bind``) return plain ``MagicMock``, while async calls (``execute``, ``commit``,
    ``flush``, ``refresh``, ``merge``, ``delete``, ``get``, ``scalar``, ``scalars``,
    ``rollback``, ``close``) return ``AsyncMock``.

    This avoids the 'coroutine was never awaited' warnings that bare ``AsyncMock()``
    produces when sync methods are called without ``await``.

    Returns:
        MagicMock instance spec'd to AsyncSession.

    """
    return MagicMock(spec=AsyncSession)


POSTGRES_CONTAINER_IMAGE = "postgres:18-alpine"

TEST_DATABASE_DSN = "postgresql://test:test@localhost:5432/test"
"""Standard test database DSN for unit tests that mock the database layer."""


@pytest.fixture(scope="session")
@ignore_unused_fixture
def postgres_container() -> Generator[str]:
    """Create and manage PostgreSQL test container.

    Returns:
        PostgreSQL connection URL with asyncpg driver

    Raises:
        pytest.skip: If Docker daemon is unavailable

    """
    # testcontainers starts a persistent "Ryuk" reaper container on first container
    # start and opens a TCP socket to it for the life of the pytest session. That
    # socket is never closed by testcontainers on its own, which leaks at interpreter
    # shutdown (ResourceWarning: unclosed socket). Reaper.delete_instance() closes
    # the socket and stops the ryuk container cleanly; we invoke it in the session
    # teardown below.
    from testcontainers.core.container import DockerContainer, Reaper
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy
    from testcontainers.postgres import PostgresContainer

    container: PostgresContainer | None = None
    try:
        if not docker_daemon_available():
            pytest.skip("PostgreSQL container could not be started: Docker daemon unavailable")

        container = PostgresContainer(POSTGRES_CONTAINER_IMAGE)
        container.with_command("postgres -c wal_level=logical -c max_replication_slots=16 -c max_wal_senders=16")
        container.waiting_for(
            LogMessageWaitStrategy("database system is ready to accept connections").with_startup_timeout(
                timedelta(seconds=60)
            )
        )
        container.start()

        # Get sync URL and convert to async (handle both psycopg2 and plain postgresql URLs)
        database_url = container.get_connection_url()
        async_url = database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
            "postgresql://", "postgresql+asyncpg://"
        )

        yield async_url

    except (RuntimeError, OSError) as e:
        pytest.skip(f"PostgreSQL container could not be started: {e}")
    finally:
        # Podman's force-remove path waits its full stop grace for running containers.
        # Stop PostgreSQL and Ryuk first; dependent engines have already been disposed.
        if container is not None:
            wrapped_container = container.get_wrapped_container()
            if wrapped_container is not None:
                with contextlib.suppress(Exception):
                    wrapped_container.stop(timeout=1)
            with contextlib.suppress(Exception):
                container.stop()

        reaper = cast("DockerContainer | None", vars(Reaper).get("_container"))
        if reaper is not None:
            wrapped_reaper = reaper.get_wrapped_container()
            if wrapped_reaper is not None:
                with contextlib.suppress(Exception):
                    wrapped_reaper.stop(timeout=1)
        with contextlib.suppress(Exception):
            Reaper.delete_instance()


@pytest.fixture
@ignore_unused_fixture
async def async_engine(postgres_container: str) -> AsyncGenerator[AsyncEngine]:
    """Create async database engine using the PostgreSQL connection.

    Args:
        postgres_container: PostgreSQL connection URL from postgres_container fixture

    Yields:
        AsyncEngine instance configured for testing with NullPool

    """
    engine = create_async_engine(postgres_container, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
@ignore_unused_fixture
def async_session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create async session factory.

    Args:
        async_engine: AsyncEngine from async_engine fixture

    Returns:
        async_sessionmaker for creating database sessions

    """
    return async_sessionmaker(async_engine, expire_on_commit=False)


@pytest.fixture
@ignore_unused_fixture
async def async_session(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Provide an async database session for testing.

    Args:
        async_session_factory: Session factory from async_session_factory fixture

    Yields:
        AsyncSession instance for test use

    """
    async with async_session_factory() as session:
        yield session


def get_async_engine(database_url: str) -> AsyncEngine:
    """Create async database engine for testing.

    Args:
        database_url: PostgreSQL connection URL with asyncpg driver

    Returns:
        AsyncEngine instance configured for testing

    """
    return create_async_engine(database_url, poolclass=NullPool)


def get_async_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory for testing.

    Args:
        engine: AsyncEngine instance

    Returns:
        async_sessionmaker for creating database sessions

    """
    return async_sessionmaker(engine, expire_on_commit=False)

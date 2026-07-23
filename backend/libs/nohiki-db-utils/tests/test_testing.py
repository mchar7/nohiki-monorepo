"""Tests for testing module fixtures and utilities.

These verify the test infrastructure itself works correctly.
"""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import AsyncGenerator, Callable, Generator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from nohiki_db_utils.testing import (
    POSTGRES_CONTAINER_IMAGE,
    create_mock_session,
    get_async_engine,
    get_async_sessionmaker,
)
from nohiki_db_utils.testing import (
    async_engine as testing_async_engine,
)
from nohiki_db_utils.testing import (
    async_session as testing_async_session,
)
from nohiki_db_utils.testing import (
    async_session_factory as testing_async_session_factory,
)
from nohiki_db_utils.testing import (
    postgres_container as testing_postgres_container,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_raw_postgres_container = cast(
    Callable[[], Generator[str]],
    inspect.unwrap(testing_postgres_container),
)
_raw_async_engine = cast(
    Callable[[str], AsyncGenerator[AsyncEngine]],
    inspect.unwrap(testing_async_engine),
)
_raw_async_session_factory = cast(
    Callable[[AsyncEngine], async_sessionmaker[AsyncSession]],
    inspect.unwrap(testing_async_session_factory),
)
_raw_async_session = cast(
    Callable[[async_sessionmaker[AsyncSession]], AsyncGenerator[AsyncSession]],
    inspect.unwrap(testing_async_session),
)


class TestTestingModuleUnitPaths:
    """Unit tests for database testing helpers and fixture lifecycles."""

    def test_create_mock_session_uses_async_session_spec(self) -> None:
        """Test that the lightweight session mock distinguishes async methods."""
        session = create_mock_session()

        assert isinstance(session, MagicMock)
        session.add(object())
        session.add.assert_called_once()
        assert isinstance(session.commit, AsyncMock)

    def test_postgres_container_yields_url_and_cleans_up(self) -> None:
        """Test the container fixture lifecycle without a Docker daemon."""
        container = MagicMock()
        container.get_connection_url.return_value = "postgresql://test:test@localhost:5432/test"
        reaper_container = MagicMock()
        wait_strategy = MagicMock()
        wait_strategy.with_startup_timeout.return_value = wait_strategy

        with (
            patch("nohiki_db_utils.testing.docker_daemon_available", return_value=True),
            patch("testcontainers.postgres.PostgresContainer", return_value=container) as container_type,
            patch(
                "testcontainers.core.wait_strategies.LogMessageWaitStrategy",
                return_value=wait_strategy,
            ),
            patch("testcontainers.core.container.Reaper._container", reaper_container),
            patch("testcontainers.core.container.Reaper.delete_instance") as delete_reaper,
        ):
            generator = _raw_postgres_container()
            assert next(generator) == "postgresql+asyncpg://test:test@localhost:5432/test"
            with contextlib.suppress(StopIteration):
                next(generator)

        container_type.assert_called_once_with(POSTGRES_CONTAINER_IMAGE)
        container.waiting_for.assert_called_once_with(wait_strategy)
        container.start.assert_called_once()
        container.get_wrapped_container.return_value.stop.assert_called_once_with(timeout=1)
        container.stop.assert_called_once()
        reaper_container.get_wrapped_container.return_value.stop.assert_called_once_with(timeout=1)
        delete_reaper.assert_called_once()

    def test_postgres_container_skips_runtime_error(self) -> None:
        """Test that container startup errors use the documented skip pathway."""
        with (
            patch("nohiki_db_utils.testing.docker_daemon_available", return_value=True),
            patch(
                "testcontainers.postgres.PostgresContainer",
                side_effect=RuntimeError("Docker unavailable"),
            ),
            patch("testcontainers.core.container.Reaper._container", None),
            patch("testcontainers.core.container.Reaper.delete_instance"),
        ):
            generator = _raw_postgres_container()
            with pytest.raises(pytest.skip.Exception, match="Docker unavailable"):
                next(generator)

    @pytest.mark.asyncio
    async def test_async_engine_fixture_disposes_engine(self) -> None:
        """Test that the async engine fixture always disposes its engine."""
        engine = MagicMock(spec=AsyncEngine)
        engine.dispose = AsyncMock()

        with patch("nohiki_db_utils.testing.create_async_engine", return_value=engine) as create_engine:
            generator = _raw_async_engine("postgresql+asyncpg://test:test@localhost/test")
            assert await generator.__anext__() is engine
            with pytest.raises(StopAsyncIteration):
                await generator.__anext__()

        create_engine.assert_called_once()
        engine.dispose.assert_awaited_once()

    def test_async_session_factory_fixture_configures_sessions(self) -> None:
        """Test that the session factory fixture disables expiration."""
        engine = MagicMock(spec=AsyncEngine)
        factory = MagicMock(spec=async_sessionmaker)

        with patch("nohiki_db_utils.testing.async_sessionmaker", return_value=factory) as factory_type:
            assert _raw_async_session_factory(engine) is factory

        factory_type.assert_called_once_with(engine, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_async_session_fixture_yields_session(self) -> None:
        """Test that the session fixture enters and exits its session context."""
        session = MagicMock(spec=AsyncSession)
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        session_context.__aexit__ = AsyncMock(return_value=None)
        factory = MagicMock(spec=async_sessionmaker)
        factory.return_value = session_context

        generator = _raw_async_session(factory)
        assert await generator.__anext__() is session
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

        session_context.__aenter__.assert_awaited_once()
        session_context.__aexit__.assert_awaited_once()

    def test_get_async_engine_uses_null_pool(self) -> None:
        """Test that the engine helper uses the isolated NullPool configuration."""
        engine = MagicMock(spec=AsyncEngine)

        with patch("nohiki_db_utils.testing.create_async_engine", return_value=engine) as create_engine:
            assert get_async_engine("postgresql+asyncpg://test:test@localhost/test") is engine

        _, kwargs = create_engine.call_args
        assert kwargs["poolclass"] is sa.NullPool

    def test_get_async_sessionmaker_disables_expiration(self) -> None:
        """Test that the sessionmaker helper disables expiration."""
        engine = MagicMock(spec=AsyncEngine)
        factory = MagicMock(spec=async_sessionmaker)

        with patch("nohiki_db_utils.testing.async_sessionmaker", return_value=factory) as factory_type:
            assert get_async_sessionmaker(engine) is factory

        factory_type.assert_called_once_with(engine, expire_on_commit=False)


@pytest.mark.integration
@pytest.mark.requires_docker
class TestTestingModuleFixtures:
    """Integration tests for testing module fixtures."""

    def test_postgres_container_returns_connection_url(self, postgres_container: str) -> None:
        """Verify postgres_container fixture returns a valid connection URL."""
        assert postgres_container.startswith("postgresql+asyncpg://")
        assert "@" in postgres_container

    @pytest.mark.asyncio
    async def test_async_engine_is_connected(self, async_engine: AsyncEngine) -> None:
        """Verify async_engine fixture provides a connected engine."""
        async with async_engine.connect() as conn:
            result = await conn.execute(sa.text("SELECT 1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1

    @pytest.mark.asyncio
    async def test_async_session_factory_creates_sessions(
        self, async_session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Verify async_session_factory can create sessions."""
        async with async_session_factory() as session:
            result = await session.execute(sa.text("SELECT 1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1

    @pytest.mark.asyncio
    async def test_async_session_is_functional(self, async_session: AsyncSession) -> None:
        """Verify async_session fixture provides a functional session."""
        result = await async_session.execute(sa.text("SELECT 1"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == 1


class TestTestingModuleHelpers:
    """Tests for testing module helper functions."""

    @pytest.mark.integration
    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_get_async_engine_creates_engine(self, postgres_container: str) -> None:
        """Verify get_async_engine creates a functional engine."""
        from nohiki_db_utils.testing import get_async_engine

        engine = get_async_engine(postgres_container)
        async with engine.connect() as conn:
            result = await conn.execute(sa.text("SELECT 1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1
        await engine.dispose()

    @pytest.mark.integration
    @pytest.mark.requires_docker
    @pytest.mark.asyncio
    async def test_get_async_sessionmaker_creates_factory(self, async_engine: AsyncEngine) -> None:
        """Verify get_async_sessionmaker creates a functional session factory."""
        from nohiki_db_utils.testing import get_async_sessionmaker

        factory = get_async_sessionmaker(async_engine)
        async with factory() as session:
            result = await session.execute(sa.text("SELECT 1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == 1

"""Tests for testing module fixtures and utilities.

These verify the test infrastructure itself works correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


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

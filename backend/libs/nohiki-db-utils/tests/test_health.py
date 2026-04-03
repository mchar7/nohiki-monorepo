"""Tests for database health probe."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.health import (
    DatabaseHealthProbe,
    ensure_database_ready,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


class TestDatabaseHealthProbe:
    """Tests for DatabaseHealthProbe."""

    def test_name_property(self) -> None:
        """Probe name is 'database'."""
        mock_engine = MagicMock(spec=AsyncEngine)
        probe = DatabaseHealthProbe(mock_engine)
        assert probe.name == "database"

    @pytest.mark.asyncio
    async def test_check_healthy(self, async_engine: AsyncEngine) -> None:
        """Returns healthy when database responds correctly."""
        probe = DatabaseHealthProbe(async_engine, check_migrations=False)
        result = await probe.check()
        assert result.is_healthy()
        assert result.name == "database"

    @pytest.mark.asyncio
    async def test_check_with_degraded_latency(self, async_engine: AsyncEngine) -> None:
        """Returns degraded when latency exceeds threshold."""
        probe = DatabaseHealthProbe(
            async_engine,
            check_migrations=False,
            degraded_threshold_ms=0.0001,
        )
        result = await probe.check()
        assert result.status.value in ("healthy", "degraded")

    @pytest.mark.asyncio
    async def test_check_connection_failure(self) -> None:
        """Returns unhealthy when connection fails."""
        from contextlib import asynccontextmanager

        mock_engine = MagicMock(spec=AsyncEngine)
        mock_conn = MagicMock()
        mock_conn.scalar = MagicMock(side_effect=SQLAlchemyError("Connection refused"))

        @asynccontextmanager
        async def mock_connect() -> AsyncIterator[MagicMock]:
            yield mock_conn

        mock_engine.connect = mock_connect

        probe = DatabaseHealthProbe(mock_engine, check_migrations=False)
        result = await probe.check()
        assert result.status.value == "unhealthy"
        assert "Connection refused" in result.message

    @pytest.mark.asyncio
    async def test_check_with_migration_check_disabled(self, async_engine: AsyncEngine) -> None:
        """check_migrations=False skips migration state check."""
        probe = DatabaseHealthProbe(async_engine, check_migrations=False)
        result = await probe.check()
        assert result.is_healthy()

    @pytest.mark.asyncio
    async def test_check_migration_not_healthy(self) -> None:
        """Returns unhealthy when migration state is not healthy (lines 87-89)."""
        mock_engine = MagicMock(spec=AsyncEngine)

        with patch("nohiki_db_utils.migrations.get_migration_state") as mock_get_state:
            mock_state = MagicMock()
            mock_state.is_healthy.return_value = False
            mock_state.status = "failed"
            mock_state.to_dict.return_value = {"status": "failed"}
            mock_get_state.return_value = mock_state

            probe = DatabaseHealthProbe(mock_engine, check_migrations=True)
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "Migrations not completed" in result.message

    @pytest.mark.asyncio
    async def test_check_unexpected_select_result(self) -> None:
        """Returns unhealthy when SELECT 1 returns unexpected value (line 101)."""
        from contextlib import asynccontextmanager

        mock_engine = MagicMock(spec=AsyncEngine)
        mock_conn = MagicMock()

        # Mock the async scalar method properly
        mock_conn.scalar = AsyncMock(return_value=42)  # Unexpected value, not 1

        @asynccontextmanager
        async def mock_connect() -> AsyncIterator[MagicMock]:
            yield mock_conn

        mock_engine.connect = mock_connect

        probe = DatabaseHealthProbe(mock_engine, check_migrations=False)
        result = await probe.check()

        assert result.status.value == "unhealthy"
        assert "unexpected value" in result.message
        assert "42" in result.message

    @pytest.mark.asyncio
    async def test_check_timeout_error(self) -> None:
        """Returns unhealthy on TimeoutError (line 108)."""
        from contextlib import asynccontextmanager

        mock_engine = MagicMock(spec=AsyncEngine)
        mock_conn = MagicMock()

        @asynccontextmanager
        async def mock_connect() -> AsyncIterator[MagicMock]:
            yield mock_conn

        mock_engine.connect = mock_connect

        with patch("nohiki_db_utils.health.asyncio.timeout") as mock_timeout:
            mock_timeout.side_effect = TimeoutError()

            probe = DatabaseHealthProbe(mock_engine, check_migrations=False, timeout_seconds=0.1)
            result = await probe.check()

            assert result.status.value == "unhealthy"
            assert "timeout" in result.message.lower()


class TestEnsureDatabaseReady:
    """Tests for ensure_database_ready function."""

    @pytest.mark.asyncio
    async def test_succeeds_when_db_available(self, async_engine: AsyncEngine) -> None:
        """Returns successfully when database is available."""
        await ensure_database_ready(async_engine, timeout_seconds=5.0)

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self) -> None:
        """Raises RuntimeError when database unavailable after timeout."""
        from contextlib import asynccontextmanager

        mock_engine = MagicMock(spec=AsyncEngine)
        mock_conn = MagicMock()
        mock_conn.scalar = MagicMock(side_effect=SQLAlchemyError("Connection refused"))

        @asynccontextmanager
        async def mock_connect() -> AsyncIterator[MagicMock]:
            yield mock_conn

        mock_engine.connect = mock_connect

        with pytest.raises(RuntimeError, match="Database unavailable"):
            await ensure_database_ready(
                mock_engine,
                timeout_seconds=0.1,
                retry_interval_seconds=0.05,
            )

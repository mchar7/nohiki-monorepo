"""Tests for database migration CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki_db_utils.migrations.cli import _run_migration, migrate_cli
from nohiki_db_utils.migrations.state import MigrationError


def _make_async_noop() -> tuple[MagicMock, MagicMock]:
    """Create a MagicMock that records calls and returns a real coroutine.

    Avoids AsyncMock which leaks unawaited coroutines during GC on Python 3.14.

    Returns:
        Tuple of (mock_function, call_recorder). The mock_function can be used
        as a patch target. The call_recorder captures keyword arguments.
    """
    recorder = MagicMock()

    async def _async_side_effect(**kwargs: object) -> None:
        recorder(**kwargs)

    mock_fn = MagicMock(side_effect=_async_side_effect)
    return mock_fn, recorder


class TestRunMigration:
    """Tests for _run_migration async function."""

    @pytest.mark.asyncio
    async def test_raises_when_service_name_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test MigrationError raised when SERVICE_NAME env var is not set."""
        monkeypatch.delenv("SERVICE_NAME", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(MigrationError, match="SERVICE_NAME"):
            await _run_migration()

    @pytest.mark.asyncio
    async def test_raises_when_database_url_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test MigrationError raised when DATABASE_URL env var is not set."""
        monkeypatch.setenv("SERVICE_NAME", "test-service")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(MigrationError, match="DATABASE_URL"):
            await _run_migration()

    @pytest.mark.asyncio
    async def test_calls_coordination_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test _run_migration passes correct defaults to run_migrations_with_coordination."""
        monkeypatch.setenv("SERVICE_NAME", "test-service")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
        monkeypatch.delenv("MIGRATION_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("ALEMBIC_CONFIG_PATH", raising=False)

        mock_fn, recorder = _make_async_noop()
        with patch(
            "nohiki_db_utils.migrations.cli.run_migrations_with_coordination",
            mock_fn,
        ):
            await _run_migration()

            recorder.assert_called_once_with(
                service_name="test-service",
                database_url="postgresql+asyncpg://user:pass@localhost/testdb",
                timeout_seconds=120,
                alembic_config_path="alembic.ini",
            )

    @pytest.mark.asyncio
    async def test_uses_custom_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test _run_migration respects MIGRATION_TIMEOUT_SECONDS env var."""
        monkeypatch.setenv("SERVICE_NAME", "test-service")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
        monkeypatch.setenv("MIGRATION_TIMEOUT_SECONDS", "60")
        monkeypatch.delenv("ALEMBIC_CONFIG_PATH", raising=False)

        mock_fn, recorder = _make_async_noop()
        with patch(
            "nohiki_db_utils.migrations.cli.run_migrations_with_coordination",
            mock_fn,
        ):
            await _run_migration()

            recorder.assert_called_once_with(
                service_name="test-service",
                database_url="postgresql+asyncpg://user:pass@localhost/testdb",
                timeout_seconds=60,
                alembic_config_path="alembic.ini",
            )

    @pytest.mark.asyncio
    async def test_uses_custom_alembic_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test _run_migration respects ALEMBIC_CONFIG_PATH env var."""
        monkeypatch.setenv("SERVICE_NAME", "test-service")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
        monkeypatch.delenv("MIGRATION_TIMEOUT_SECONDS", raising=False)
        monkeypatch.setenv("ALEMBIC_CONFIG_PATH", "custom.ini")

        mock_fn, recorder = _make_async_noop()
        with patch(
            "nohiki_db_utils.migrations.cli.run_migrations_with_coordination",
            mock_fn,
        ):
            await _run_migration()

            recorder.assert_called_once_with(
                service_name="test-service",
                database_url="postgresql+asyncpg://user:pass@localhost/testdb",
                timeout_seconds=120,
                alembic_config_path="custom.ini",
            )


class TestMigrateCli:
    """Tests for migrate_cli entrypoint."""

    def test_success_exits_normally(self) -> None:
        """Test migrate_cli returns cleanly on successful migration."""
        # Patch _run_migration to prevent coroutine creation (avoids GC leak warnings)
        with (
            patch("nohiki_db_utils.migrations.cli._run_migration", new=lambda: None),
            patch("nohiki_db_utils.migrations.cli.asyncio.run"),
        ):
            migrate_cli()  # Should not raise

    def test_exits_on_migration_error(self) -> None:
        """Test migrate_cli calls sys.exit(1) on MigrationError."""
        with (
            patch("nohiki_db_utils.migrations.cli._run_migration", new=lambda: None),
            patch(
                "nohiki_db_utils.migrations.cli.asyncio.run",
                side_effect=MigrationError("fail"),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            migrate_cli()

    def test_exits_on_keyboard_interrupt(self) -> None:
        """Test migrate_cli calls sys.exit(1) on KeyboardInterrupt."""
        with (
            patch("nohiki_db_utils.migrations.cli._run_migration", new=lambda: None),
            patch(
                "nohiki_db_utils.migrations.cli.asyncio.run",
                side_effect=KeyboardInterrupt,
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            migrate_cli()

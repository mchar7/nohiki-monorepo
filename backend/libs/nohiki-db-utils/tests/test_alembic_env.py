"""Tests for alembic environment utilities.

Consolidated URL conversion tests are in test_migrations.py (TestUrlConversion).
This file covers the remaining alembic_env functionality.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from nohiki_db_utils.alembic_env import (
    _normalize_to_sync_url,
    configure_offline_context,
    create_schema_if_not_exists,
    get_sync_database_url,
    run_online_migrations,
)
from sqlalchemy import Column, Integer, MetaData, Table


class TestNormalizeToSyncUrl:
    """Tests for _normalize_to_sync_url function (for 100% coverage)."""

    def test_converts_asyncpg_to_psycopg(self) -> None:
        """Test conversion from asyncpg to psycopg driver."""
        asyncpg_url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        result = _normalize_to_sync_url(asyncpg_url)
        assert result == "postgresql+psycopg://user:pass@localhost:5432/db"

    def test_adds_psycopg_to_plain_postgresql(self) -> None:
        """Test adding psycopg driver to plain postgresql URL."""
        plain_url = "postgresql://user:pass@localhost:5432/db"
        result = _normalize_to_sync_url(plain_url)
        assert result == "postgresql+psycopg://user:pass@localhost:5432/db"

    def test_leaves_psycopg_unchanged(self) -> None:
        """Test that psycopg URLs are returned unchanged."""
        psycopg_url = "postgresql+psycopg://user:pass@localhost:5432/db"
        result = _normalize_to_sync_url(psycopg_url)
        assert result == psycopg_url

    def test_handles_url_with_query_params(self) -> None:
        """Test conversion preserves query parameters."""
        url_with_params = "postgresql+asyncpg://user:pass@localhost/db?sslmode=require"
        result = _normalize_to_sync_url(url_with_params)
        assert result == "postgresql+psycopg://user:pass@localhost/db?sslmode=require"


class TestGetSyncDatabaseUrl:
    """Tests for get_sync_database_url function."""

    def test_uses_environment_variable_first(self) -> None:
        """Test that DATABASE_URL env var takes precedence."""
        mock_config = MagicMock()
        mock_config.get_main_option.return_value = "postgresql://from-config/db"

        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://from-env/db"}):
            result = get_sync_database_url(mock_config)
            assert result == "postgresql+psycopg://from-env/db"

    def test_falls_back_to_config(self) -> None:
        """Test fallback to alembic.ini config when env var not set."""
        mock_config = MagicMock()
        mock_config.get_main_option.return_value = "postgresql://from-config/db"

        with patch.dict(os.environ, {}, clear=True):
            result = get_sync_database_url(mock_config)
            assert result == "postgresql+psycopg://from-config/db"

    def test_raises_when_no_url_found(self) -> None:
        """Test ValueError when no database URL is available."""
        mock_config = MagicMock()
        mock_config.get_main_option.return_value = None

        with (
            patch.dict(os.environ, {}, clear=True),
            pytest.raises(ValueError, match="No database URL found"),
        ):
            get_sync_database_url(mock_config)

    def test_raises_for_non_postgresql_url(self) -> None:
        """Test ValueError for non-PostgreSQL URLs."""
        mock_config = MagicMock()
        mock_config.get_main_option.return_value = None

        with (
            patch.dict(os.environ, {"DATABASE_URL": "mysql://localhost/db"}),
            pytest.raises(ValueError, match="Expected PostgreSQL URL"),
        ):
            get_sync_database_url(mock_config)


class TestCreateSchemaIfNotExists:
    """Tests for create_schema_if_not_exists function."""

    def test_creates_schema(self) -> None:
        """Test schema creation with proper SQL."""
        mock_connection = MagicMock()
        mock_connection.execute = MagicMock()
        mock_connection.commit = MagicMock()

        create_schema_if_not_exists(mock_connection, "test_schema")

        mock_connection.execute.assert_called_once()
        mock_connection.commit.assert_called_once()

        call_args = mock_connection.execute.call_args
        assert "CREATE SCHEMA IF NOT EXISTS test_schema" in str(call_args[0][0])


class TestConfigureOfflineContext:
    """Tests for configure_offline_context function."""

    @patch("nohiki_db_utils.alembic_env.context")
    def test_configures_context_with_defaults(self, mock_context: MagicMock) -> None:
        """Test offline context configuration with default parameters."""
        metadata = MetaData()
        Table("test", metadata, Column("id", Integer, primary_key=True))

        configure_offline_context(
            url="postgresql+psycopg://localhost/db",
            target_metadata=metadata,
        )

        mock_context.configure.assert_called_once()
        call_kwargs = mock_context.configure.call_args.kwargs

        assert call_kwargs["url"] == "postgresql+psycopg://localhost/db"
        assert call_kwargs["target_metadata"] is metadata
        assert call_kwargs["literal_binds"] is True
        assert call_kwargs["dialect_opts"] == {"paramstyle": "named"}
        assert call_kwargs["include_schemas"] is True
        assert call_kwargs["version_table_schema"] is None

    @patch("nohiki_db_utils.alembic_env.context")
    def test_configures_context_with_custom_params(self, mock_context: MagicMock) -> None:
        """Test offline context configuration with custom parameters."""
        metadata = MetaData()

        configure_offline_context(
            url="postgresql+psycopg://localhost/db",
            target_metadata=metadata,
            version_table_schema="migrations",
            include_schemas=False,
        )

        call_kwargs = mock_context.configure.call_args.kwargs
        assert call_kwargs["version_table_schema"] == "migrations"
        assert call_kwargs["include_schemas"] is False

    @patch("nohiki_db_utils.alembic_env.context")
    def test_runs_migrations(self, mock_context: MagicMock) -> None:
        """Test that migrations are run after configuration."""
        metadata = MetaData()

        configure_offline_context(
            url="postgresql+psycopg://localhost/db",
            target_metadata=metadata,
        )

        mock_context.begin_transaction.assert_called_once()
        mock_context.run_migrations.assert_called_once()


class TestRunOnlineMigrations:
    """Tests for run_online_migrations function."""

    @patch("nohiki_db_utils.alembic_env.create_engine")
    @patch("nohiki_db_utils.alembic_env.context")
    @patch("nohiki_db_utils.alembic_env.create_schema_if_not_exists")
    def test_runs_with_schema_creation(
        self,
        mock_create_schema: MagicMock,
        mock_context: MagicMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test online migrations with schema creation enabled."""
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_connection)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_create_engine.return_value = mock_engine

        metadata = MetaData()

        run_online_migrations(
            url="postgresql+psycopg://localhost/db",
            target_metadata=metadata,
            version_table_schema="migrations",
            create_schema=True,
        )

        mock_create_schema.assert_called_once_with(mock_connection, "migrations")
        mock_context.configure.assert_called_once()
        mock_context.run_migrations.assert_called_once()
        mock_engine.dispose.assert_called_once()

    @patch("nohiki_db_utils.alembic_env.create_engine")
    @patch("nohiki_db_utils.alembic_env.context")
    def test_runs_without_schema_creation(
        self,
        mock_context: MagicMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test online migrations with schema creation disabled."""
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_connection)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_create_engine.return_value = mock_engine

        metadata = MetaData()

        run_online_migrations(
            url="postgresql+psycopg://localhost/db",
            target_metadata=metadata,
            version_table_schema="migrations",
            create_schema=False,
        )

        mock_context.configure.assert_called_once()
        assert mock_context.configure.call_args.kwargs["version_table_schema"] == "migrations"

    @patch("nohiki_db_utils.alembic_env.create_engine")
    @patch("nohiki_db_utils.alembic_env.context")
    def test_skips_schema_creation_when_no_schema(
        self,
        mock_context: MagicMock,
        mock_create_engine: MagicMock,
    ) -> None:
        """Test that schema is not created when version_table_schema is None."""
        mock_engine = MagicMock()
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_connection)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=None)
        mock_create_engine.return_value = mock_engine

        metadata = MetaData()

        run_online_migrations(
            url="postgresql+psycopg://localhost/db",
            target_metadata=metadata,
            version_table_schema=None,
            create_schema=True,
        )

        mock_context.configure.assert_called_once()
        assert mock_context.configure.call_args.kwargs["version_table_schema"] is None

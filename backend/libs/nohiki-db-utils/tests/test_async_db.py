"""Tests for async_db module lifecycle management."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.async_db import (
    DatabaseConnectionConfig,
    DatabaseDependencies,
    _dict_to_hashable,
    _engine_registry,
    _from_hashable,
    _get_async_engine_cached,
    _get_async_sessionmaker_cached,
    close_all_engines,
    db_session,
    get_async_engine,
    get_async_sessionmaker,
)
from nohiki_db_utils.testing import create_mock_session


@pytest.fixture(autouse=True)
def _clear_sessionmaker_cache() -> Generator[None]:
    _get_async_sessionmaker_cached.cache_clear()
    yield
    _get_async_sessionmaker_cached.cache_clear()


class MockDatabaseConfig:
    """Mock database config implementing DatabaseConnectionConfig protocol."""

    def __init__(
        self,
        connection_string: str = "postgresql+asyncpg://user:password@localhost/testdb",
    ) -> None:
        """Initialize with connection string."""
        self._connection_string = connection_string

    @property
    def connection_string(self) -> str:
        return self._connection_string

    def get_connect_args(self) -> dict[str, Any]:
        return {}


class TestDatabaseConnectionConfigProtocol:
    """Tests for DatabaseConnectionConfig protocol."""

    def test_mock_implements_protocol(self) -> None:
        """Verify MockDatabaseConfig implements DatabaseConnectionConfig protocol."""
        config = MockDatabaseConfig()
        assert isinstance(config, DatabaseConnectionConfig)

    def test_protocol_requires_connection_string(self) -> None:
        """Verify protocol requires connection_string property."""
        config = MockDatabaseConfig("postgresql+asyncpg://custom:pass@db/mydb")
        assert config.connection_string == "postgresql+asyncpg://custom:pass@db/mydb"

    def test_protocol_requires_get_connect_args(self) -> None:
        """Verify protocol requires get_connect_args method."""
        config = MockDatabaseConfig()
        assert config.get_connect_args() == {}


class TestDictToHashable:
    """Tests for _dict_to_hashable helper function."""

    def test_none_returns_none(self) -> None:
        """Verify None input returns None."""
        result = _dict_to_hashable(None)
        assert result is None

    def test_simple_dict(self) -> None:
        """Verify simple dict is converted to hashable tuple."""
        result = _dict_to_hashable({"a": 1, "b": 2})
        assert isinstance(result, tuple)
        # Should be sorted by key
        assert ("a", 1) in result
        assert ("b", 2) in result

    def test_nested_dict(self) -> None:
        """Verify nested dict is converted recursively."""
        result = _dict_to_hashable({"outer": {"inner": "value"}})
        assert isinstance(result, tuple)
        assert result is not None

    def test_dict_with_list(self) -> None:
        """Verify dict with list values is converted."""
        result = _dict_to_hashable({"items": [1, 2, 3]})
        assert isinstance(result, tuple)


class TestFromHashable:
    """Tests for _from_hashable helper function."""

    def test_non_tuple_returns_unchanged(self) -> None:
        """Verify non-tuple values are returned unchanged."""
        assert _from_hashable("string") == "string"
        assert _from_hashable(123) == 123
        assert _from_hashable(None) is None

    def test_empty_tuple_returns_unchanged(self) -> None:
        """Verify empty tuple is returned unchanged."""
        result = _from_hashable(())
        assert result == ()

    def test_tuple_of_tuples_converted_to_dict(self) -> None:
        """Verify tuple of key-value tuples is converted to dict."""
        hashable = (("a", 1), ("b", 2))
        result = _from_hashable(hashable)
        assert result == {"a": 1, "b": 2}


class TestEngineRegistry:
    """Tests for engine registry functionality."""

    def test_engine_registry_starts_empty(self) -> None:
        """Verify engine registry is a dict."""
        assert isinstance(_engine_registry, dict)

    @pytest.mark.asyncio
    async def test_close_all_engines_disposes_connections(self) -> None:
        """Verify close_all_engines disposes all cached engines."""
        # Create mock engines
        mock_engine1 = AsyncMock()
        mock_engine2 = AsyncMock()

        # Add to registry
        _engine_registry["test1"] = mock_engine1
        _engine_registry["test2"] = mock_engine2

        await close_all_engines()

        # Verify engines were disposed
        mock_engine1.dispose.assert_awaited_once()
        mock_engine2.dispose.assert_awaited_once()

        # Verify registry is cleared
        assert len(_engine_registry) == 0

    @pytest.mark.asyncio
    async def test_close_all_engines_clears_sessionmaker_cache(self) -> None:
        """Verify close_all_engines clears the sessionmaker cache."""
        from nohiki_db_utils.async_db import _get_async_sessionmaker_cached

        # Clear registry first
        _engine_registry.clear()

        with patch.object(_get_async_sessionmaker_cached, "cache_clear") as mock_cache_clear:
            await close_all_engines()
            mock_cache_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_engines_idempotent(self) -> None:
        """Verify calling close_all_engines multiple times is safe."""
        # Clear registry
        _engine_registry.clear()

        # Should not raise
        await close_all_engines()
        await close_all_engines()
        await close_all_engines()

    @pytest.mark.asyncio
    async def test_close_all_engines_empty_registry(self) -> None:
        """Verify close_all_engines works with empty registry."""
        _engine_registry.clear()

        # Should not raise
        await close_all_engines()


class TestGetAsyncEngineCached:
    """Tests for _get_async_engine_cached function."""

    def test_returns_cached_engine(self) -> None:
        """Verify same engine is returned for same parameters."""
        # Clear registry first
        _engine_registry.clear()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            # First call creates engine
            engine1 = _get_async_engine_cached("postgresql+asyncpg://user:password@localhost/testdb", None, echo=False)

            # Second call returns cached engine
            engine2 = _get_async_engine_cached("postgresql+asyncpg://user:password@localhost/testdb", None, echo=False)

            assert engine1 is engine2
            mock_create.assert_called_once()

        # Clean up
        _engine_registry.clear()

    def test_different_params_create_different_engines(self) -> None:
        """Verify different parameters create different engines."""
        _engine_registry.clear()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine1 = MagicMock()
            mock_engine2 = MagicMock()
            mock_create.side_effect = [mock_engine1, mock_engine2]

            engine1 = _get_async_engine_cached("postgresql+asyncpg://user:pass@localhost/db1", None, echo=False)
            engine2 = _get_async_engine_cached("postgresql+asyncpg://user:pass@localhost/db2", None, echo=False)

            assert engine1 is not engine2
            assert mock_create.call_count == 2

        _engine_registry.clear()

    def test_echo_param_affects_caching(self) -> None:
        """Verify echo parameter is part of cache key."""
        _engine_registry.clear()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine1 = MagicMock()
            mock_engine2 = MagicMock()
            mock_create.side_effect = [mock_engine1, mock_engine2]

            engine1 = _get_async_engine_cached("postgresql+asyncpg://user:pass@localhost/db", None, echo=False)
            engine2 = _get_async_engine_cached("postgresql+asyncpg://user:pass@localhost/db", None, echo=True)

            assert engine1 is not engine2

        _engine_registry.clear()


class TestGetAsyncEngine:
    """Tests for get_async_engine public function."""

    def test_uses_cached_engine(self) -> None:
        """Verify get_async_engine uses caching."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            engine1 = get_async_engine(config)
            engine2 = get_async_engine(config)

            assert engine1 is engine2
            mock_create.assert_called_once()

        _engine_registry.clear()

    def test_respects_echo_parameter(self) -> None:
        """Verify echo parameter is passed through."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            get_async_engine(config, echo=True)

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["echo"] is True

        _engine_registry.clear()


class TestGetAsyncSessionmaker:
    """Tests for get_async_sessionmaker function."""

    def test_returns_sessionmaker(self) -> None:
        """Verify get_async_sessionmaker returns a sessionmaker."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            sessionmaker = get_async_sessionmaker(config)

            # Should be callable
            assert callable(sessionmaker)

        _engine_registry.clear()


class TestDatabaseDependencies:
    """Tests for DatabaseDependencies class."""

    def test_initialization(self) -> None:
        """Verify DatabaseDependencies initializes correctly."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            deps = DatabaseDependencies(config)

            assert deps._sessionmaker is not None

        _engine_registry.clear()

    @pytest.mark.asyncio
    async def test_get_async_db_yields_session(self) -> None:
        """Verify get_async_db yields a session."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            deps = DatabaseDependencies(config)

            # Mock the sessionmaker to return a mock session
            mock_session = create_mock_session()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            with patch.object(deps, "_sessionmaker", return_value=mock_session):
                async for session in deps.get_async_db():
                    assert session is mock_session

        _engine_registry.clear()

    @pytest.mark.asyncio
    async def test_get_outbox_raises_when_no_schema(self) -> None:
        """Verify get_outbox raises ValueError when outbox_schema not set."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            # Initialize without outbox_schema
            deps = DatabaseDependencies(config)

            with pytest.raises(ValueError, match="outbox_schema"):
                await deps.get_outbox().__anext__()

        _engine_registry.clear()

    @pytest.mark.asyncio
    async def test_get_outbox_yields_writer_with_schema(self) -> None:
        """Verify get_outbox yields OutboxWriter when outbox_schema is set."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            # Initialize with outbox_schema
            deps = DatabaseDependencies(config, outbox_schema="test_schema")

            # Mock the sessionmaker to return a mock session
            mock_session = create_mock_session()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            with patch.object(deps, "_sessionmaker", return_value=mock_session):
                async for writer in deps.get_outbox():
                    assert writer is not None
                    assert writer._schema == "test_schema"

        _engine_registry.clear()


class TestDbSession:
    """Tests for db_session function."""

    def test_returns_session(self) -> None:
        """Verify db_session returns a session."""
        _engine_registry.clear()

        config = MockDatabaseConfig()

        with patch("nohiki_db_utils.async_db.create_async_engine") as mock_create:
            mock_engine = MagicMock()
            mock_create.return_value = mock_engine

            session = db_session(config)

            # Should return something (the actual session type depends on SQLAlchemy)
            assert session is not None

        _engine_registry.clear()

"""Tests for core/db module."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session


@pytest.mark.asyncio
async def test_get_async_db_yields_session() -> None:
    """Test that get_async_db yields a database session."""
    from bff_service.core.db import get_async_db

    mock_session = create_mock_session()
    mock_db_deps = MagicMock()

    async def mock_get_async_db_gen() -> AsyncGenerator[AsyncMock]:
        yield mock_session

    mock_db_deps.get_async_db.return_value = mock_get_async_db_gen()

    with patch("bff_service.core.db._get_db_deps", return_value=mock_db_deps):
        async_gen = get_async_db()
        session = await anext(async_gen)

        assert session is mock_session


@pytest.mark.asyncio
async def test_get_db_deps_creates_database_dependencies() -> None:
    """Test that _get_db_deps creates DatabaseDependencies from settings."""
    from bff_service.core.db import _get_db_deps

    # Clear the cache
    _get_db_deps.cache_clear()

    with patch("bff_service.core.db.DatabaseDependencies") as mock_db_deps_class:
        mock_db_deps_instance = MagicMock()
        mock_db_deps_class.return_value = mock_db_deps_instance

        result = _get_db_deps()

        assert result is mock_db_deps_instance
        mock_db_deps_class.assert_called_once()


def test_get_db_deps_raises_when_database_not_configured() -> None:
    """Test that _get_db_deps raises RuntimeError when database is not configured."""
    from bff_service.core.db import _get_db_deps

    # Clear the cache
    _get_db_deps.cache_clear()

    # Mock settings with database = None
    mock_settings = MagicMock()
    mock_settings.database = None

    with (
        patch("bff_service.core.db.get_settings", return_value=mock_settings),
        pytest.raises(RuntimeError, match="DATABASE must be configured"),
    ):
        _get_db_deps()


def test_get_db_deps_cached_returns_same_instance() -> None:
    """Test that _get_db_deps uses caching and returns the same instance."""
    from bff_service.core.db import _get_db_deps

    # Clear the cache
    _get_db_deps.cache_clear()

    with patch("bff_service.core.db.DatabaseDependencies") as mock_db_deps_class:
        mock_db_deps_instance = MagicMock()
        mock_db_deps_class.return_value = mock_db_deps_instance

        # First call
        result1 = _get_db_deps()

        # Second call - should return cached result
        result2 = _get_db_deps()

        assert result1 is result2
        # DatabaseDependencies should only be instantiated once
        assert mock_db_deps_class.call_count == 1

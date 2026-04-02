"""Shared test fixtures and utilities for nohiki-db-utils tests."""

from __future__ import annotations

import contextlib

import pytest
from nohiki_db_utils.testing import (
    async_engine,
    async_session,
    async_session_factory,
    get_async_engine,
    get_async_sessionmaker,
    postgres_container,
)
from nohiki_test_utils import setup_test_secrets

# Re-export all testing fixtures
__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "get_async_engine",
    "get_async_sessionmaker",
    "postgres_container",
    "setup_test_secrets",
]


class MockDatabaseConfig:
    """Mock database config implementing DatabaseConfig protocol for tests."""

    def __init__(
        self,
        connection_string: str = "postgresql+asyncpg://user:password@localhost/testdb",
    ) -> None:
        """Initialize with connection string."""
        self._connection_string = connection_string

    @property
    def connection_string(self) -> str:
        return self._connection_string

    def get_connect_args(self) -> dict[str, object]:
        return {}


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Close testcontainers Reaper socket after test session ends."""
    _ = (session, exitstatus)
    with contextlib.suppress(Exception):
        from testcontainers.core.container import Reaper

        Reaper.delete_instance()

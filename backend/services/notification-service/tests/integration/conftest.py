"""Fixtures for notification-service integration tests."""

from __future__ import annotations

from nohiki_db_utils.testing import (
    async_engine,
    async_session,
    async_session_factory,
    postgres_container,
)

__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "postgres_container",
]

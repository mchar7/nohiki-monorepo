"""Database dependencies for user-auth-service.

FastAPI dependencies for database sessions and outbox writers.
Import these in routers to use with Depends().
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import TYPE_CHECKING

from nohiki_db_utils import DatabaseDependencies

if TYPE_CHECKING:
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings


@lru_cache
def _get_db_deps() -> DatabaseDependencies:
    """Get or create database dependencies singleton."""
    settings = get_settings()
    return DatabaseDependencies(settings.database, outbox_schema=settings.database.schema_name)


async def get_async_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency for database sessions."""
    async for session in _get_db_deps().get_async_db():
        yield session


async def get_outbox() -> AsyncGenerator[OutboxWriter]:
    """FastAPI dependency for outbox writer."""
    async for outbox in _get_db_deps().get_outbox():
        yield outbox

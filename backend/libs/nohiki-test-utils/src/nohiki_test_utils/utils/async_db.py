"""Async database utilities for testing."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.sql.schema import MetaData


def make_async_url(url: str) -> str:
    """Convert a database URL to use asyncpg driver for async operations."""
    if url.startswith("postgresql://") and "postgresql+asyncpg://" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://")
    return url


@lru_cache(maxsize=1)
def get_async_engine(url: str) -> AsyncEngine:
    """Get or create an async SQLAlchemy engine with caching."""
    async_url = make_async_url(url)
    return create_async_engine(async_url, echo=False)


@lru_cache(maxsize=1)
def get_async_sessionmaker(url: str) -> async_sessionmaker[AsyncSession]:
    """Get or create an async session maker with caching."""
    engine = get_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def reset_db(engine: AsyncEngine, base_metadata: MetaData) -> None:
    """Reset database by dropping and recreating all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(base_metadata.drop_all)
        await conn.run_sync(base_metadata.create_all)

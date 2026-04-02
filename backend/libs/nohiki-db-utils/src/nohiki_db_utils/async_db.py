"""Shared async database utilities for nohiki microservices.

- Prepared statement caching for asyncpg driver
- Connection pooling with pre-ping for reliability
- Conservative pool limits for multi-pod scaling
- SSL configuration via DatabaseSettings.get_connect_args()
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from sqlalchemy.sql.schema import MetaData

from .outbox import OutboxWriter

type _PairsTuple = tuple[tuple[object, object], ...]
PAIR_LENGTH: Final[int] = 2

# Engine registry for tracking created engines so they can be properly disposed
_engine_registry: dict[str, AsyncEngine] = {}


@runtime_checkable
class DatabaseConnectionConfig(Protocol):
    """Protocol for database configuration that provides connection string and SSL args."""

    @property
    def connection_string(self) -> str:
        """Database connection string."""
        ...

    def get_connect_args(self) -> dict[str, Any]:
        """Get connect_args for SQLAlchemy async engine."""
        ...


_DEFAULT_CONNECT_ARGS: dict[str, Any] = {
    "prepared_statement_cache_size": 256,
    "statement_cache_size": 256,
}


def _dict_to_hashable(d: dict[str, Any] | None) -> tuple[tuple[str, Any], ...] | None:
    """Convert a dictionary to a hashable tuple for caching purposes."""
    if d is None:
        return None

    def _make_hashable(obj: object) -> object:
        if isinstance(obj, dict):
            return tuple(sorted((_make_hashable(k), _make_hashable(v)) for k, v in obj.items()))
        if isinstance(obj, list):
            return tuple(_make_hashable(item) for item in obj)
        return obj

    return tuple(sorted((k, _make_hashable(v)) for k, v in d.items()))


def _is_tuple_of_pairs(obj: object) -> bool:
    """Check if object is a tuple of key-value pairs."""
    if not isinstance(obj, tuple) or not obj:
        return False
    return all(isinstance(item, tuple) and len(item) == PAIR_LENGTH for item in obj)


def _from_hashable(obj: object) -> dict[str, object] | object:
    """Convert hashable tuple back to dict structure."""
    if _is_tuple_of_pairs(obj):
        pairs = cast(_PairsTuple, obj)
        return {str(_from_hashable(k)): _from_hashable(v) for k, v in pairs}
    return obj


def _get_async_engine_cached(
    url: str, connect_args_hashable: tuple[tuple[str, Any], ...] | None, *, echo: bool
) -> AsyncEngine:
    """Create an async SQLAlchemy engine with caching via registry.

    Uses a module-level registry instead of @lru_cache to allow
    proper disposal of engines during shutdown.
    """
    cache_key = f"{url}:{connect_args_hashable}:{echo}"

    if cache_key in _engine_registry:
        return _engine_registry[cache_key]

    connect_args: dict[str, Any] = {}
    if connect_args_hashable is not None:
        result = _from_hashable(connect_args_hashable)
        if isinstance(result, dict):
            connect_args = cast(dict[str, Any], result)

    merged_connect_args: dict[str, Any] = _DEFAULT_CONNECT_ARGS | connect_args

    engine = create_async_engine(
        url,
        echo=echo,
        connect_args=merged_connect_args,
        pool_size=3,
        max_overflow=2,
        pool_timeout=10,
        pool_pre_ping=True,
        pool_recycle=300,
    )

    _engine_registry[cache_key] = engine
    return engine


def get_async_engine(db_settings: DatabaseConnectionConfig, *, echo: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine from DatabaseSettings or compatible config."""
    ssl_args = db_settings.get_connect_args()
    merged_args = _DEFAULT_CONNECT_ARGS | ssl_args
    connect_args_hashable = _dict_to_hashable(merged_args)
    return _get_async_engine_cached(db_settings.connection_string, connect_args_hashable, echo=echo)


@lru_cache(maxsize=1)
def _get_async_sessionmaker_cached(
    url: str, connect_args_hashable: tuple[tuple[str, Any], ...] | None
) -> async_sessionmaker[AsyncSession]:
    """Create an async session maker with caching."""
    engine = _get_async_engine_cached(url, connect_args_hashable, echo=False)
    return async_sessionmaker(engine, expire_on_commit=False)


def get_async_sessionmaker(
    db_settings: DatabaseConnectionConfig,
) -> async_sessionmaker[AsyncSession]:
    """Get or create an async session maker from DatabaseSettings or compatible config."""
    ssl_args = db_settings.get_connect_args()
    merged_args = _DEFAULT_CONNECT_ARGS | ssl_args
    connect_args_hashable = _dict_to_hashable(merged_args)
    return _get_async_sessionmaker_cached(db_settings.connection_string, connect_args_hashable)


class DatabaseDependencies:
    """Container for database-related FastAPI dependencies.

    Usage in service config.py:
        from nohiki_db_utils import DatabaseDependencies

        _settings = get_settings()
        db_deps = DatabaseDependencies(_settings.database, outbox_schema="my_schema")
        get_async_db = db_deps.get_async_db
        get_outbox = db_deps.get_outbox
    """

    def __init__(
        self,
        db_settings: DatabaseConnectionConfig,
        outbox_schema: str | None = None,
    ) -> None:
        """Initialize database dependencies from DatabaseSettings or compatible config.

        Args:
            db_settings: Database configuration.
            outbox_schema: Schema containing the outbox table (required if get_outbox() is used).

        """
        self._sessionmaker = get_async_sessionmaker(db_settings)
        self._outbox_schema = outbox_schema

    async def get_async_db(self) -> AsyncGenerator[AsyncSession]:
        """FastAPI dependency for database sessions."""
        async with self._sessionmaker() as session:
            yield session

    async def get_outbox(self) -> AsyncGenerator[OutboxWriter]:
        """FastAPI dependency for outbox writer.

        Raises:
            ValueError: If outbox_schema was not provided to constructor.

        """
        if not self._outbox_schema:
            msg = "get_outbox() requires outbox_schema to be set in DatabaseDependencies constructor"
            raise ValueError(msg)
        async with self._sessionmaker() as session:
            yield OutboxWriter(schema=self._outbox_schema, db=session)


def db_session(db_settings: DatabaseConnectionConfig) -> AsyncSession:
    """Get an async database session as a context manager."""
    return get_async_sessionmaker(db_settings)()


async def reset_db(engine: AsyncEngine, base_metadata: MetaData) -> None:
    """Reset database by dropping and recreating all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(base_metadata.drop_all)
        await conn.run_sync(base_metadata.create_all)


async def close_all_engines() -> None:
    """Dispose all cached database engines in parallel and clear caches.

    Call this from FastAPI lifespan shutdown to properly close
    database connection pools.

    Safe to call multiple times - subsequent calls are no-ops.
    """
    if _engine_registry:
        async with asyncio.TaskGroup() as tg:
            for engine in _engine_registry.values():
                tg.create_task(engine.dispose())

    _engine_registry.clear()
    _get_async_sessionmaker_cached.cache_clear()

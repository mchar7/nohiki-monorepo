"""The service's Alembic revision applies cleanly and carries the TTL schema.

The revision is edited in place rather than extended (DATABASE.md, clean-cut
deployment), so any schema change lands as a diff to `001_initial_migration.py`.
Every other test builds the schema from SQLAlchemy metadata, which means a typo
in the revision's DDL would otherwise reach a deploy unnoticed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from notification_service.services.outbox.expiry_sweep import EXPIRABLE_STATUSES
from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = "notification_schema"


def _alembic_config() -> Config:
    config = Config(str(_SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    # alembic.ini carries no path_separator; without one Alembic emits a
    # DeprecationWarning, which this suite escalates to an error.
    config.set_main_option("path_separator", "os")
    return config


@pytest.fixture
async def migrated_schema(
    async_engine: AsyncEngine,
    postgres_container: str,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None]:
    """Run `alembic upgrade head` against the container, drop the schema after."""
    monkeypatch.setenv("DATABASE_URL", postgres_container)
    async with async_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))

    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    try:
        yield
    finally:
        async with async_engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))


@pytest.mark.asyncio
@pytest.mark.usefixtures("migrated_schema")
async def test_messages_carries_the_expiry_column(async_engine: AsyncEngine) -> None:
    """`expires_at` exists as a nullable timestamptz, as the sweep expects."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'messages' AND column_name = 'expires_at'"
            ),
            {"schema": _SCHEMA},
        )
        row = result.one_or_none()

    assert row is not None, "the revision must create messages.expires_at"
    assert row.data_type == "timestamp with time zone"
    assert row.is_nullable == "YES"


@pytest.mark.asyncio
@pytest.mark.usefixtures("migrated_schema")
async def test_sweep_index_exists_alongside_the_queue_index(async_engine: AsyncEngine) -> None:
    """The sweep's partial index is created and the queue index survives."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND tablename = 'messages'"),
            {"schema": _SCHEMA},
        )
        index_names = {row.indexname for row in result.all()}

    assert "ix_messages_expires_at" in index_names
    assert "ix_messages_queue" in index_names


@pytest.mark.asyncio
@pytest.mark.usefixtures("migrated_schema")
async def test_expiry_index_covers_exactly_the_states_the_sweep_claims(async_engine: AsyncEngine) -> None:
    """A predicate narrower than the sweep's silently degrades the claim to a table scan."""
    async with async_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = :schema AND indexname = 'ix_messages_expires_at'"),
            {"schema": _SCHEMA},
        )
        indexdef = result.scalar_one()

    assert "WHERE" in indexdef
    assert "expires_at IS NOT NULL" in indexdef
    predicate_states = {name for name in ("pending", "waiting_for_render", "retrying") if f"'{name}'" in indexdef}
    assert predicate_states == {status.value for status in EXPIRABLE_STATUSES}
    assert "'sent'" not in indexdef
    assert "'cancelled'" not in indexdef
    assert "'failed'" not in indexdef

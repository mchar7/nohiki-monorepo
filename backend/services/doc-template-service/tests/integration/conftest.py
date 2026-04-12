"""PostgreSQL fixtures for document-template persistence contracts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from doc_template_service.db.models import SCHEMA_NAME
from nohiki_db_utils.testing import async_engine, postgres_container

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

__all__ = ["async_engine", "async_session", "postgres_container"]

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def setup_database_schema(postgres_container: str) -> None:
    """Apply the service's real migrations once to PostgreSQL."""
    sync_url = postgres_container.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    config = Config(str(_SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    config.set_main_option("path_separator", "os")

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


@pytest.fixture
async def async_session(
    setup_database_schema: None,
    async_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Provide an isolated session against the migrated schema."""
    _ = setup_database_schema
    async with async_engine.begin() as connection:
        await connection.execute(
            sa.text(f"TRUNCATE TABLE {SCHEMA_NAME}.document_templates, {SCHEMA_NAME}.outbox RESTART IDENTITY CASCADE")
        )

    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session

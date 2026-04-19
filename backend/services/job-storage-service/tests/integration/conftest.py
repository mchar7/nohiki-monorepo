"""Integration fixtures for job-storage-service.

The schema is created exactly once per pytest session by running the real
alembic migration against the testcontainer; per-test isolation truncates
all tables touched by tests rather than recreating the schema. Running the
authoritative migration (instead of hand-rolled DDL that drifts) is what
``test_migration_parity`` verifies, so any divergence between the migration
and the SQLAlchemy models surfaces as a real test failure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from job_storage_service.db.models import SCHEMA_NAME

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

# Path to the service root so alembic can locate alembic.ini and versions/.
_SERVICE_ROOT = Path(__file__).resolve().parents[2]

# Tables truncated between tests. listing_versions has a FK to listings, so
# CASCADE handles cleanup. The alembic_version table is preserved so the
# migration is treated as already applied across tests.
_TRUNCATE_TABLES: tuple[str, ...] = (
    "listings",
    "listing_versions",
    "listing_ingest_saga",
    "outbox",
    "processed_events",
)


@pytest.fixture(scope="session")
def setup_database_schema(postgres_container: str) -> None:
    """Run the real alembic migration against the testcontainer once per session.

    ``postgres_container`` yields an asyncpg URL; alembic needs the sync
    psycopg form. ``alembic_env`` reads ``DATABASE_URL`` first and falls back
    to the alembic.ini setting: we set the env var temporarily so a
    developer's local ``DATABASE_URL`` (pointing at a real cluster) can't
    leak into the test migration.
    """
    sync_url = postgres_container.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    cfg = Config(str(_SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    # Alembic 1.16 deprecates implicit prepend_sys_path splitting; the test
    # config raises on DeprecationWarning, so we set the new option explicitly.
    cfg.set_main_option("path_separator", "os")

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


@pytest.fixture
async def async_session(
    setup_database_schema: None,
    async_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Provide a per-test session against the migrated schema.

    Truncates the data tables before each test (CASCADE handles the
    listing_versions FK) so rows from earlier tests don't bleed across.
    The migration is preserved between tests; only row data is reset.
    """
    _ = setup_database_schema

    from sqlalchemy.ext.asyncio import async_sessionmaker

    truncate_sql = sa.text(
        f"TRUNCATE TABLE {', '.join(f'{SCHEMA_NAME}.{t}' for t in _TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"
    )
    async with async_engine.begin() as conn:
        await conn.execute(truncate_sql)

    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        yield session

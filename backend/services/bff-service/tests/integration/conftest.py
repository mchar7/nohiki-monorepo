"""Integration fixtures requiring a real PostgreSQL instance via testcontainers.

Creates the ``bff_schema`` and the ``job_listing_projections`` table directly
from the SQLAlchemy model metadata so tests exercise actual SQL rather than
mocks. Shape mirrors ``001_initial_migration.py`` for the subset of columns
touched by the auth-listings query path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
import sqlalchemy as sa
from bff_service.db.models import JobListingProjection
from bff_service.db.models.base import SCHEMA_NAME
from nohiki_db_utils.testing import (
    async_engine,
    async_session,
    async_session_factory,
    postgres_container,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "postgres_container",
]


@pytest.fixture
async def setup_auth_listings_schema(async_engine: AsyncEngine) -> None:
    """Create ``bff_schema`` + ``job_listing_projections`` in the testcontainer.

    Drops any existing schema first so each test starts from a clean slate.
    Only the single table and its indexes needed by the auth-listings query
    path are created: keeps fixture surface minimal and fast.
    """
    table = cast("sa.Table", JobListingProjection.__table__)
    async with async_engine.begin() as conn:
        await conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE"))
        await conn.execute(sa.text(f"CREATE SCHEMA {SCHEMA_NAME}"))
        await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=False))

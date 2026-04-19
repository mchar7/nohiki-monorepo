"""Migration vs SQLAlchemy model parity check.

Asserts that the schema produced by the alembic migration matches what
``Listing.__table__`` and ``ListingIngestSaga.__table__`` advertise. This
is the canary that fails when the migration and the models drift apart --
a far more useful failure mode than every integration test silently
running against hand-rolled DDL that lies about the real schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from job_storage_service.db.models import SCHEMA_NAME, Listing, ListingIngestSaga
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


# Coarse type compatibility groups: SQLAlchemy reports many concrete types
# (VARCHAR/CHARACTER VARYING, TEXT, JSONB, etc.). Postgres ``data_type`` from
# ``information_schema`` is canonical, so we map the SQLAlchemy column type
# class onto the set of postgres types it may legitimately compile to.
_TYPE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "TEXT": frozenset({"text"}),
    "VARCHAR": frozenset({"character varying"}),
    "STRING": frozenset({"character varying", "text"}),
    "INTEGER": frozenset({"integer"}),
    "BIGINT": frozenset({"bigint"}),
    "FLOAT": frozenset({"double precision", "real"}),
    "JSONB": frozenset({"jsonb"}),
    "UUID": frozenset({"uuid"}),
    "DATETIME": frozenset({"timestamp with time zone", "timestamp without time zone"}),
    "ARRAY": frozenset({"ARRAY"}),
    "TSVECTOR": frozenset({"tsvector"}),
    "ENUM": frozenset({"USER-DEFINED"}),
}


def _expected_pg_types(column: sa.ColumnElement[object]) -> frozenset[str]:
    """Resolve the postgres ``data_type`` strings that ``column`` may compile to."""
    type_name = type(column.type).__name__.upper()

    # Enum-typed columns from SQLAlchemy report as USER-DEFINED in information_schema
    # because they reference a custom postgres ENUM type, not a built-in scalar.
    if isinstance(column.type, sa.Enum):
        return _TYPE_COMPATIBILITY["ENUM"]

    # ARRAY columns report as 'ARRAY' regardless of element type.
    if isinstance(column.type, sa.ARRAY):
        return _TYPE_COMPATIBILITY["ARRAY"]

    return _TYPE_COMPATIBILITY.get(type_name, frozenset({type_name.lower()}))


async def _fetch_columns(session: AsyncSession, table_name: str) -> dict[str, tuple[str, bool]]:
    """Return ``{column_name: (data_type, nullable)}`` for the given live table."""
    result = await session.execute(
        text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table"
        ),
        {"schema": SCHEMA_NAME, "table": table_name},
    )
    return {row.column_name: (row.data_type, row.is_nullable == "YES") for row in result.fetchall()}


async def _fetch_check_constraints(session: AsyncSession, table_name: str) -> set[str]:
    """Return the set of CHECK constraint names attached to ``table_name``."""
    # The ``::regclass`` cast collides with asyncpg's ``:`` bind parameter parser
    # if combined with a bound string, so we resolve the table OID in a separate
    # parameterized query first and then look up its constraints by oid.
    oid_result = await session.execute(
        text(
            "SELECT c.oid FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND c.relname = :table"
        ),
        {"schema": SCHEMA_NAME, "table": table_name},
    )
    oid_row = oid_result.first()
    if oid_row is None:
        return set()

    result = await session.execute(
        text("SELECT conname FROM pg_constraint WHERE conrelid = :oid AND contype = 'c'"),
        {"oid": oid_row.oid},
    )
    return {row.conname for row in result.fetchall()}


async def _fetch_indexes(session: AsyncSession, table_name: str) -> dict[str, str]:
    """Return ``{indexname: indexdef}`` for the given live table."""
    result = await session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :schema AND tablename = :table"),
        {"schema": SCHEMA_NAME, "table": table_name},
    )
    return {row.indexname: row.indexdef for row in result.fetchall()}


def _assert_columns_match(
    table_name: str,
    declared: sa.FromClause,
    live: dict[str, tuple[str, bool]],
) -> None:
    """Assert the declared model columns match what's live in the database.

    Reports any column missing from the DB, any DB column not declared on the
    model (drift), and any nullability or type mismatch with a clear message.
    """
    declared_names = set(declared.columns.keys())
    live_names = set(live.keys())

    missing_in_db = declared_names - live_names
    extra_in_db = live_names - declared_names

    if missing_in_db:
        pytest.fail(f"{table_name}: columns declared on model but missing in DB: {sorted(missing_in_db)}")
    if extra_in_db:
        pytest.fail(f"{table_name}: columns in DB but not declared on model (drift): {sorted(extra_in_db)}")

    mismatches: list[str] = []
    for name, column in declared.columns.items():
        live_type, live_nullable = live[name]
        expected_types = _expected_pg_types(column)

        if live_type not in expected_types:
            mismatches.append(
                f"  {name}: model type {type(column.type).__name__} -> {sorted(expected_types)} "
                f"but DB reports '{live_type}'"
            )
        if column.nullable != live_nullable:
            mismatches.append(f"  {name}: model nullable={column.nullable} but DB nullable={live_nullable}")

    if mismatches:
        pytest.fail(f"{table_name}: column drift\n" + "\n".join(mismatches))


class TestListingsParity:
    """``listings`` table: the post-enrichment canonical row store."""

    async def test_columns_match_model(self, async_session: AsyncSession) -> None:
        """Every column declared on Listing must exist with matching nullability+type."""
        live = await _fetch_columns(async_session, "listings")
        _assert_columns_match("listings", Listing.__table__, live)

    async def test_check_constraints_present(self, async_session: AsyncSession) -> None:
        """The five CHECK constraints declared in the migration must exist on listings."""
        expected = {
            "chk_description_length",
            "chk_company_name_length",
            "chk_experience_range",
            "chk_compensation_json",
            "chk_location_json",
        }
        live = await _fetch_check_constraints(async_session, "listings")
        missing = expected - live
        if missing:
            pytest.fail(f"listings: missing CHECK constraints: {sorted(missing)} (live: {sorted(live)})")

    async def test_dedup_unique_index_present(self, async_session: AsyncSession) -> None:
        """The cross-source dedup unique index must exist."""
        indexes = await _fetch_indexes(async_session, "listings")
        if "ix_listings_dedup" not in indexes:
            pytest.fail(f"listings: missing ix_listings_dedup (live: {sorted(indexes)})")
        # Confirm uniqueness and column target.
        idx_def = indexes["ix_listings_dedup"].lower()
        assert "unique" in idx_def
        assert "dedup_hash" in idx_def

    async def test_listing_url_unique_index_present(self, async_session: AsyncSession) -> None:
        """listing_url must have a unique index so duplicate canonical rows are impossible."""
        indexes = await _fetch_indexes(async_session, "listings")
        if "ix_listings_url" not in indexes:
            pytest.fail(f"listings: missing ix_listings_url (live: {sorted(indexes)})")
        idx_def = indexes["ix_listings_url"].lower()
        assert "unique" in idx_def, f"ix_listings_url is not UNIQUE: {idx_def}"
        assert "listing_url" in idx_def


class TestIngestSagaParity:
    """``listing_ingest_saga`` table: in-flight ingest tracking."""

    async def test_columns_match_model(self, async_session: AsyncSession) -> None:
        """Every column declared on ListingIngestSaga must exist with matching nullability+type."""
        live = await _fetch_columns(async_session, "listing_ingest_saga")
        _assert_columns_match("listing_ingest_saga", ListingIngestSaga.__table__, live)

    async def test_check_constraints_present(self, async_session: AsyncSession) -> None:
        """Saga invariants must be enforced as CHECK constraints in the DB."""
        live = await _fetch_check_constraints(async_session, "listing_ingest_saga")
        expected = {"chk_received_le_expected", "chk_listing_url_nonempty"}
        missing = expected - live
        if missing:
            pytest.fail(f"listing_ingest_saga: missing CHECK constraints: {sorted(missing)} (live: {sorted(live)})")

    async def test_partial_unique_index_on_pending_url(self, async_session: AsyncSession) -> None:
        """The partial unique index must enforce one PENDING saga per URL."""
        indexes = await _fetch_indexes(async_session, "listing_ingest_saga")
        idx_def = indexes.get("ix_listing_ingest_saga_url_pending")
        if idx_def is None:
            pytest.fail(f"listing_ingest_saga: missing ix_listing_ingest_saga_url_pending (live: {sorted(indexes)})")

        normalized = idx_def.lower()
        # Must be UNIQUE on listing_url with a partial predicate restricting to PENDING.
        assert "unique" in normalized, f"index not UNIQUE: {idx_def}"
        assert "listing_url" in normalized, f"index not on listing_url: {idx_def}"
        assert "where" in normalized, f"index missing WHERE clause: {idx_def}"
        assert "pending" in normalized, f"index missing PENDING predicate: {idx_def}"

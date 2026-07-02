"""Tests for auth-listings SQL query builders.

Verifies that ``fetch_primary_candidates``, ``fetch_backfill_candidates``,
and ``fetch_global_candidates`` build correct SQLAlchemy statements and
execute them against the session.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bff_service.core.config import AuthListingsSettings
from bff_service.services.auth_listings.queries import (
    _auth_listing_columns,
    _quality_predicates,
    fetch_backfill_candidates,
    fetch_global_candidates,
    fetch_primary_candidates,
)


def _make_settings(
    *,
    max_listing_age_days: int = 30,
    min_title_length: int = 10,
    primary_candidate_limit: int = 500,
    backfill_candidate_limit: int = 300,
    backfill_threshold: int = 5,
    max_listings_returned: int = 150,
    max_per_company: int = 5,
    rate_limit_per_minute: int = 60,
) -> AuthListingsSettings:
    """Build AuthListingsSettings with sensible test defaults."""
    return AuthListingsSettings(
        secret="test-secret",
        max_listing_age_days=max_listing_age_days,
        min_title_length=min_title_length,
        primary_candidate_limit=primary_candidate_limit,
        backfill_candidate_limit=backfill_candidate_limit,
        backfill_threshold=backfill_threshold,
        max_listings_returned=max_listings_returned,
        max_per_company=max_per_company,
        rate_limit_per_minute=rate_limit_per_minute,
    )


EXPECTED_COLUMN_COUNT = 8


class TestAuthListingColumns:
    """Tests for _auth_listing_columns helper."""

    def test_returns_expected_column_count(self) -> None:
        """Column tuple has exactly 8 columns for the auth-listing response."""
        cols = _auth_listing_columns()
        assert len(cols) == EXPECTED_COLUMN_COUNT

    def test_column_names(self) -> None:
        """Columns match the expected projection fields."""
        cols = _auth_listing_columns()
        names = {c.key for c in cols}
        assert names == {
            "title",
            "company_name",
            "location_raw",
            "work_arrangement",
            "required_skills",
            "posted_at",
            "language",
            "country_code",
        }


class TestQualityPredicates:
    """Tests for _quality_predicates helper."""

    def test_returns_nonempty_list(self) -> None:
        """Predicates list is non-empty for valid settings."""
        predicates = _quality_predicates(_make_settings())
        assert len(predicates) > 0

    def test_predicate_count_is_stable(self) -> None:
        """There are exactly 6 quality predicates."""
        expected_predicates = 6
        predicates = _quality_predicates(_make_settings())
        assert len(predicates) == expected_predicates


class TestFetchPrimaryCandidates:
    """Tests for fetch_primary_candidates."""

    @pytest.mark.asyncio
    async def test_executes_query_on_session(self) -> None:
        """Calls db.execute with a SELECT statement."""
        fake_rows = [SimpleNamespace(title="Job A"), SimpleNamespace(title="Job B")]
        result_mock = MagicMock()
        result_mock.all.return_value = fake_rows
        db = AsyncMock()
        db.execute.return_value = result_mock

        rows = await fetch_primary_candidates(db, "USA", _make_settings())

        db.execute.assert_awaited_once()
        assert rows == fake_rows

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rows(self) -> None:
        """Returns empty sequence when no candidates match."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = AsyncMock()
        db.execute.return_value = result_mock

        rows = await fetch_primary_candidates(db, "USA", _make_settings())

        assert rows == []

    @pytest.mark.asyncio
    async def test_statement_contains_country_filter(self) -> None:
        """Generated SQL includes the country_code equality predicate."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = AsyncMock()
        db.execute.return_value = result_mock

        await fetch_primary_candidates(db, "USA", _make_settings())

        stmt = db.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "country_code" in compiled


class TestFetchBackfillCandidates:
    """Tests for fetch_backfill_candidates."""

    @pytest.mark.asyncio
    async def test_executes_query_on_session(self) -> None:
        """Calls db.execute with a SELECT statement."""
        fake_rows = [SimpleNamespace(title="Backfill Job")]
        result_mock = MagicMock()
        result_mock.all.return_value = fake_rows
        db = AsyncMock()
        db.execute.return_value = result_mock

        rows = await fetch_backfill_candidates(db, "USA", _make_settings())

        db.execute.assert_awaited_once()
        assert rows == fake_rows

    @pytest.mark.asyncio
    async def test_excludes_specified_country(self) -> None:
        """Generated SQL excludes the specified country code."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = AsyncMock()
        db.execute.return_value = result_mock

        await fetch_backfill_candidates(db, "USA", _make_settings())

        stmt = db.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "country_code" in compiled
        assert "!=" in compiled or "<>" in compiled


class TestFetchGlobalCandidates:
    """Tests for fetch_global_candidates."""

    @pytest.mark.asyncio
    async def test_executes_query_on_session(self) -> None:
        """Calls db.execute with a SELECT statement."""
        fake_rows = [SimpleNamespace(title="Global Job")]
        result_mock = MagicMock()
        result_mock.all.return_value = fake_rows
        db = AsyncMock()
        db.execute.return_value = result_mock

        rows = await fetch_global_candidates(db, _make_settings())

        db.execute.assert_awaited_once()
        assert rows == fake_rows

    @pytest.mark.asyncio
    async def test_no_country_equality_filter_in_statement(self) -> None:
        """Global query has no country_code = 'X' or country_code != 'X' predicate."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = AsyncMock()
        db.execute.return_value = result_mock

        await fetch_global_candidates(db, _make_settings())

        stmt = db.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        # Quality predicates include country_code IS NOT NULL, but global
        # should NOT have country_code = 'literal' or country_code != 'literal'
        assert "country_code = '" not in compiled
        assert "country_code != '" not in compiled

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rows(self) -> None:
        """Returns empty sequence when no candidates match."""
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db = AsyncMock()
        db.execute.return_value = result_mock

        rows = await fetch_global_candidates(db, _make_settings())

        assert rows == []

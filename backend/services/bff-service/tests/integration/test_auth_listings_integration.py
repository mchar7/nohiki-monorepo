"""DB-backed integration tests for ``compile_auth_listings``.

Exercises the real SQLAlchemy query path against a testcontainer Postgres
instance. Asserts query filtering, ordering, backfill logic, diversity, and
the unknown-country global fallback through the full service orchestration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from bff_service.core.config import AuthListingsSettings
from bff_service.db.models import JobListingProjection
from bff_service.services.auth_listings.service import compile_auth_listings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.usefixtures("setup_auth_listings_schema"),
]


_TEST_SETTINGS = AuthListingsSettings(
    secret="integration-test-secret",
    max_listing_age_days=30,
    min_title_length=10,
    primary_candidate_limit=500,
    backfill_candidate_limit=300,
    backfill_threshold=5,
    max_listings_returned=150,
    max_per_company=5,
    rate_limit_per_minute=60,
)


def _insert_listing(
    *,
    country_code: str,
    title: str = "Senior Python Engineer",
    company_name: str = "Acme Corp",
    language: str | None = "en",
    posted_at: datetime | None = None,
) -> dict[str, object]:
    """Build a minimal ``JobListingProjection`` row as a mapping for bulk insert."""
    now = datetime.now(UTC)
    return {
        "id": uuid.uuid4(),
        "listing_url": f"https://example.com/jobs/{uuid.uuid4()}",
        "source": "LINKEDIN",
        "title": title,
        "company_name": company_name,
        "description": (
            "Senior Python engineer role focused on backend services. "
            "Build scalable APIs, review code, and mentor juniors. "
            "Strong async Python skills required, plus FastAPI and Postgres experience. "
            "Great team, modern stack, remote friendly."
        ),
        "location_raw": "Somewhere",
        "work_arrangement": "REMOTE",
        "seniority_level": "SENIOR",
        "language": language,
        "required_skills": ["Python", "FastAPI"],
        "version": 1,
        "raw_content_hash": uuid.uuid4().hex,
        "posted_at": posted_at or now,
        "discovered_at": now,
        "country_code": country_code,
        "latitude": None,
        "longitude": None,
    }


async def _seed(async_session: AsyncSession, rows: list[dict[str, object]]) -> None:
    """Bulk-insert raw listing rows via SQLAlchemy Core."""
    await async_session.execute(sa.insert(JobListingProjection).values(rows))
    await async_session.commit()


@pytest.mark.asyncio
async def test_primary_country_filters_by_country_code(async_session: AsyncSession) -> None:
    """Known country returns only same-country listings when pool >= backfill_threshold."""
    rows = [
        *(_insert_listing(country_code="USA", company_name=f"USA-{i}") for i in range(6)),
        *(_insert_listing(country_code="GBR", company_name=f"GBR-{i}") for i in range(4)),
    ]
    await _seed(async_session, rows)

    result = await compile_auth_listings(
        async_session,
        "USA",
        user_language="en",
        settings=_TEST_SETTINGS,
    )

    assert result.country == "USA"
    assert len(result.listings) == 6
    assert all(item.company_name.startswith("USA-") for item in result.listings)


@pytest.mark.asyncio
async def test_backfill_triggers_when_primary_below_threshold(async_session: AsyncSession) -> None:
    """Sparse primary pool supplements with international listings."""
    rows = [
        *(_insert_listing(country_code="USA", company_name=f"USA-{i}") for i in range(2)),
        *(_insert_listing(country_code="GBR", company_name=f"GBR-{i}") for i in range(4)),
        *(_insert_listing(country_code="DEU", company_name=f"DEU-{i}") for i in range(3)),
    ]
    await _seed(async_session, rows)

    result = await compile_auth_listings(
        async_session,
        "USA",
        user_language="en",
        settings=_TEST_SETTINGS,
    )

    assert result.country == "USA"
    assert len(result.listings) == 9
    companies = {item.company_name for item in result.listings}
    assert any(c.startswith("USA-") for c in companies)
    assert any(c.startswith("GBR-") for c in companies) or any(c.startswith("DEU-") for c in companies)


@pytest.mark.asyncio
async def test_unknown_country_uses_global_fallback(async_session: AsyncSession) -> None:
    """Unrecognized country pulls from all countries via the global query."""
    rows = [
        _insert_listing(country_code="USA", company_name="A"),
        _insert_listing(country_code="GBR", company_name="B"),
        _insert_listing(country_code="DEU", company_name="C"),
    ]
    await _seed(async_session, rows)

    result = await compile_auth_listings(
        async_session,
        "ZZZ",
        user_language=None,
        settings=_TEST_SETTINGS,
    )

    assert result.country == "ZZZ"
    assert len(result.listings) == 3


@pytest.mark.asyncio
async def test_quality_predicates_exclude_stale_and_short_titles(async_session: AsyncSession) -> None:
    """Stale listings, short titles, and empty companies are filtered out."""
    now = datetime.now(UTC)
    stale = now - timedelta(days=60)

    rows = [
        # Kept: recent + long title + valid company
        _insert_listing(country_code="USA", title="Senior Python Engineer", company_name="Keep"),
        # Dropped: too old
        _insert_listing(
            country_code="USA",
            title="Senior Python Engineer",
            company_name="Stale",
            posted_at=stale,
        ),
        # Dropped: title too short
        _insert_listing(country_code="USA", title="Short", company_name="ShortTitle"),
        # Dropped: empty company
        _insert_listing(country_code="USA", title="Senior Python Engineer", company_name=""),
    ]
    await _seed(async_session, rows)

    result = await compile_auth_listings(
        async_session,
        "USA",
        user_language="en",
        settings=_TEST_SETTINGS,
    )

    companies = {item.company_name for item in result.listings}
    assert companies == {"Keep"}


@pytest.mark.asyncio
async def test_diversity_filter_caps_per_company(async_session: AsyncSession) -> None:
    """No company may exceed ``max_per_company`` in the final response."""
    rows = [
        *(_insert_listing(country_code="USA", company_name="MegaCorp") for _ in range(10)),
        *(_insert_listing(country_code="USA", company_name=f"Other-{i}") for i in range(3)),
    ]
    await _seed(async_session, rows)

    settings = _TEST_SETTINGS.model_copy(update={"max_per_company": 2})

    result = await compile_auth_listings(
        async_session,
        "USA",
        user_language="en",
        settings=settings,
    )

    megacorp_count = sum(1 for item in result.listings if item.company_name == "MegaCorp")
    assert megacorp_count == 2


@pytest.mark.asyncio
async def test_ordering_prefers_recent_listings(async_session: AsyncSession) -> None:
    """Freshest listings rank first by weight (recency dominates)."""
    now = datetime.now(UTC)
    rows = [
        _insert_listing(country_code="USA", company_name="Fresh", posted_at=now),
        _insert_listing(country_code="USA", company_name="Day5", posted_at=now - timedelta(days=5)),
        _insert_listing(country_code="USA", company_name="Day20", posted_at=now - timedelta(days=20)),
        _insert_listing(country_code="USA", company_name="Pad1", posted_at=now - timedelta(days=1)),
        _insert_listing(country_code="USA", company_name="Pad2", posted_at=now - timedelta(days=2)),
        _insert_listing(country_code="USA", company_name="Pad3", posted_at=now - timedelta(days=3)),
    ]
    await _seed(async_session, rows)

    result = await compile_auth_listings(
        async_session,
        "USA",
        user_language="en",
        settings=_TEST_SETTINGS,
    )

    assert result.listings[0].company_name == "Fresh"
    assert result.listings[-1].company_name == "Day20"


@pytest.mark.asyncio
async def test_empty_database_returns_empty_listings(async_session: AsyncSession) -> None:
    """Empty table yields an empty response without raising."""
    result = await compile_auth_listings(
        async_session,
        "USA",
        user_language="en",
        settings=_TEST_SETTINGS,
    )

    assert result.country == "USA"
    assert result.listings == []

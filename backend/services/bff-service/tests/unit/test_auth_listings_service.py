"""Tests for auth-listings service orchestrator (compile_auth_listings)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from bff_service.core.config import AuthListingsSettings

# Helpers

_SERVICE_MODULE = "bff_service.services.auth_listings.service"
_TEST_SECRET = "test-secret"

# Minimum valid backfill_threshold is 5 (ge=5 constraint on AuthListingsSettings).
_MIN_THRESHOLD = 5


def _make_settings(
    *,
    secret: str = _TEST_SECRET,
    max_listing_age_days: int = 30,
    min_title_length: int = 10,
    primary_candidate_limit: int = 500,
    backfill_candidate_limit: int = 300,
    backfill_threshold: int = _MIN_THRESHOLD,
    max_listings_returned: int = 150,
    max_per_company: int = 5,
    rate_limit_per_minute: int = 60,
) -> AuthListingsSettings:
    """Build AuthListingsSettings with sensible test defaults.

    Note: backfill_threshold has ``ge=5`` so the minimum valid value is 5.
    """
    return AuthListingsSettings(
        secret=secret,
        max_listing_age_days=max_listing_age_days,
        min_title_length=min_title_length,
        primary_candidate_limit=primary_candidate_limit,
        backfill_candidate_limit=backfill_candidate_limit,
        backfill_threshold=backfill_threshold,
        max_listings_returned=max_listings_returned,
        max_per_company=max_per_company,
        rate_limit_per_minute=rate_limit_per_minute,
    )


def _make_row(
    *,
    title: str = "Senior Python Engineer",
    company_name: str = "Acme Corp",
    location_raw: str | None = "San Francisco, CA",
    work_arrangement: str | None = "REMOTE",
    required_skills: list[str] | None = None,
    posted_at: datetime | None = None,
    language: str | None = "en",
    country_code: str = "USA",
) -> SimpleNamespace:
    """Create a fake DB row matching the auth-listing column set."""
    return SimpleNamespace(
        title=title,
        company_name=company_name,
        location_raw=location_raw,
        work_arrangement=work_arrangement,
        required_skills=required_skills or ["Python", "FastAPI"],
        posted_at=posted_at or datetime.now(UTC),
        language=language,
        country_code=country_code,
    )


def _make_rows(
    count: int,
    *,
    title: str = "Senior Python Engineer",
    location_raw: str | None = "San Francisco, CA",
    work_arrangement: str | None = "REMOTE",
    required_skills: list[str] | None = None,
    posted_at: datetime | None = None,
    language: str | None = "en",
    country_code: str = "USA",
) -> list[SimpleNamespace]:
    """Create *count* rows with unique company names (avoids diversity filter collisions)."""
    return [
        _make_row(
            title=title,
            company_name=f"Company {i}",
            location_raw=location_raw,
            work_arrangement=work_arrangement,
            required_skills=required_skills,
            posted_at=posted_at,
            language=language,
            country_code=country_code,
        )
        for i in range(count)
    ]


# Response structure


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_response_is_auth_listings_response(
    mock_primary: AsyncMock,
) -> None:
    """compile_auth_listings returns an AuthListingsResponse."""
    from bff_service.services.auth_listings.schemas import AuthListingsResponse
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(6)
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    assert isinstance(result, AuthListingsResponse)
    assert result.country == "USA"
    assert len(result.listings) == 6


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_response_listings_contain_expected_fields(
    mock_primary: AsyncMock,
) -> None:
    """Each listing item has all expected fields."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    target_row = _make_row(
        title="Backend Developer",
        company_name="Startup Inc",
        location_raw="Berlin, DE",
        work_arrangement="HYBRID",
        required_skills=["Go", "K8s"],
        language="de",
    )
    # Target row + padding to exceed threshold → no backfill
    mock_primary.return_value = [target_row, *_make_rows(5)]
    db = AsyncMock()

    result = await compile_auth_listings(db, "DEU", user_language="de", settings=_make_settings())

    # Target row has same language match → should appear at/near top
    item = result.listings[0]
    assert item.title == "Backend Developer"
    assert item.company_name == "Startup Inc"
    assert item.location_raw == "Berlin, DE"
    assert item.work_arrangement == "HYBRID"
    assert item.required_skills == ["Go", "K8s"]
    assert item.language == "de"
    assert item.posted_at is not None


# Weight exclusion: AuthListingItem must not expose internal weight


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_response_excludes_weight(
    mock_primary: AsyncMock,
) -> None:
    """AuthListingItem must NOT expose the internal weight field."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(6)
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    item = result.listings[0]
    assert not hasattr(item, "weight")
    dumped = item.model_dump()
    assert "weight" not in dumped


# Backfill triggered when primary < threshold


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_backfill_candidates", new_callable=AsyncMock)
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_backfill_triggered_when_primary_below_threshold(
    mock_primary: AsyncMock,
    mock_backfill: AsyncMock,
) -> None:
    """Backfill is fetched when primary count < backfill_threshold."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    # 2 primary rows, threshold=5 → backfill triggered
    mock_primary.return_value = _make_rows(2)
    mock_backfill.return_value = [
        _make_row(company_name="Global Inc", country_code="GBR"),
    ]
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    mock_backfill.assert_awaited_once()
    assert len(result.listings) == 3


# Backfill NOT triggered when primary >= threshold


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_backfill_candidates", new_callable=AsyncMock)
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_backfill_not_triggered_when_primary_at_threshold(
    mock_primary: AsyncMock,
    mock_backfill: AsyncMock,
) -> None:
    """Backfill is NOT fetched when primary count == backfill_threshold."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(5)
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    mock_backfill.assert_not_awaited()
    assert len(result.listings) == 5


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_backfill_candidates", new_callable=AsyncMock)
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_backfill_not_triggered_when_primary_above_threshold(
    mock_primary: AsyncMock,
    mock_backfill: AsyncMock,
) -> None:
    """Backfill is NOT fetched when primary count > backfill_threshold."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(10)
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    mock_backfill.assert_not_awaited()
    assert len(result.listings) == 10


# Unknown country → global fallback


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_global_candidates", new_callable=AsyncMock)
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_unknown_country_uses_global_fallback(
    mock_primary: AsyncMock,
    mock_global: AsyncMock,
) -> None:
    """Unrecognized country code triggers global query, not primary."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_global.return_value = [
        _make_row(country_code="USA"),
        _make_row(country_code="GBR", company_name="UK Corp"),
    ]
    db = AsyncMock()

    result = await compile_auth_listings(db, "ZZZ", user_language="en", settings=_make_settings())

    mock_primary.assert_not_awaited()
    mock_global.assert_awaited_once()
    assert result.country == "ZZZ"
    assert len(result.listings) == 2


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_global_candidates", new_callable=AsyncMock)
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_known_country_does_not_use_global(
    mock_primary: AsyncMock,
    mock_global: AsyncMock,
) -> None:
    """Known country code uses primary path, not global."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(6)
    db = AsyncMock()

    await compile_auth_listings(db, "GBR", user_language="en", settings=_make_settings())

    mock_primary.assert_awaited_once()
    mock_global.assert_not_awaited()


# Diversity filter applied


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_diversity_filter_caps_per_company(
    mock_primary: AsyncMock,
) -> None:
    """Diversity filter limits listings per company to max_per_company."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    # 8 listings from the same company → capped to 2
    mock_primary.return_value = [_make_row(company_name="MegaCorp") for _ in range(8)]
    db = AsyncMock()
    settings = _make_settings(max_per_company=2, max_listings_returned=150)

    result = await compile_auth_listings(db, "USA", user_language="en", settings=settings)

    assert len(result.listings) == 2
    assert all(item.company_name == "MegaCorp" for item in result.listings)


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_diversity_filter_caps_total(
    mock_primary: AsyncMock,
) -> None:
    """Diversity filter limits total listings to max_listings_returned."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(20)
    db = AsyncMock()
    settings = _make_settings(max_per_company=5, max_listings_returned=10)

    result = await compile_auth_listings(db, "USA", user_language="en", settings=settings)

    assert len(result.listings) == 10


# Sorting by weight (recency affects weight)


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_results_sorted_by_weight_descending(
    mock_primary: AsyncMock,
) -> None:
    """Listings are sorted by computed weight descending: recent listings first."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    now = datetime.now(UTC)
    rows = [
        _make_row(title="Old Listing", company_name="A", posted_at=now - timedelta(days=25)),
        _make_row(title="Fresh Listing", company_name="B", posted_at=now),
        _make_row(title="Week Old", company_name="C", posted_at=now - timedelta(days=5)),
        _make_row(title="Pad1", company_name="D", posted_at=now - timedelta(days=1)),
        _make_row(title="Pad2", company_name="E", posted_at=now - timedelta(days=2)),
    ]
    mock_primary.return_value = rows
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    assert result.listings[0].title == "Fresh Listing"
    assert result.listings[-1].title == "Old Listing"


# Edge case: empty results


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_backfill_candidates", new_callable=AsyncMock)
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_empty_primary_and_backfill(
    mock_primary: AsyncMock,
    mock_backfill: AsyncMock,
) -> None:
    """Returns empty listings when both primary and backfill return no rows."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = []
    mock_backfill.return_value = []
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language="en", settings=_make_settings())

    assert result.listings == []
    assert result.country == "USA"


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_global_candidates", new_callable=AsyncMock)
async def test_empty_global_fallback(mock_global: AsyncMock) -> None:
    """Returns empty listings when global fallback returns no rows."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_global.return_value = []
    db = AsyncMock()

    result = await compile_auth_listings(db, "XYZ", user_language=None, settings=_make_settings())

    assert result.listings == []
    assert result.country == "XYZ"


# User language None


@pytest.mark.asyncio
@patch(f"{_SERVICE_MODULE}.fetch_primary_candidates", new_callable=AsyncMock)
async def test_none_user_language_accepted(
    mock_primary: AsyncMock,
) -> None:
    """None user_language does not raise: it means no language preference."""
    from bff_service.services.auth_listings.service import compile_auth_listings

    mock_primary.return_value = _make_rows(6)
    db = AsyncMock()

    result = await compile_auth_listings(db, "USA", user_language=None, settings=_make_settings())

    assert len(result.listings) == 6

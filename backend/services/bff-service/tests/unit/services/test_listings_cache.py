"""Tests for listings_cache module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_build_search_cache_key() -> None:
    """Test cache key building."""
    from bff_service.services.listings_cache import build_search_cache_key

    key = build_search_cache_key("Python Developer", 1, 20)
    assert key == "listings:search:python developer:1:20"


def test_build_search_cache_key_normalization() -> None:
    """Test cache key normalizes query (lowercase, strip)."""
    from bff_service.services.listings_cache import build_search_cache_key

    key = build_search_cache_key("  PYTHON  ", 2, 10)
    assert key == "listings:search:python:2:10"


def test_build_search_cache_key_isolates_response_shaping_filters() -> None:
    """Cached search pages cannot bleed across source, company, or salary filters."""
    from bff_service.services.listings_cache import build_search_cache_key

    unfiltered = build_search_cache_key("python", 1, 20)
    filtered_keys = {
        build_search_cache_key("python", 1, 20, source="linkedin"),
        build_search_cache_key("python", 1, 20, company="Acme"),
        build_search_cache_key("python", 1, 20, has_salary=True),
    }

    assert unfiltered not in filtered_keys
    assert len(filtered_keys) == 3


def test_build_search_cache_key_normalizes_filter_identity() -> None:
    """Case and surrounding whitespace do not fragment an equivalent filtered search."""
    from bff_service.services.listings_cache import build_search_cache_key

    left = build_search_cache_key(" PYTHON ", 2, 10, source=" LinkedIn ", company=" ACME ", has_salary=True)
    right = build_search_cache_key("python", 2, 10, source="linkedin", company="acme", has_salary=True)

    assert left == right


@pytest.mark.asyncio
async def test_get_cached_search_results_hit() -> None:
    """Test getting cached results when cache hit occurs."""
    cached_data = {
        "items": [
            {
                "id": "1",
                "listing_url": "https://example.com/job/1",
                "source": "example",
                "title": "Job 1",
                "company_name": "Company A",
                "description": "A test job",
                "location_raw": "New York, NY",
                "work_arrangement": "remote",
                "seniority_level": "junior",
                "language": "en",
                "required_skills": ["python"],
                "posted_at": "2024-01-01T00:00:00",
                "discovered_at": "2024-01-01T00:00:00",
                "created_at": "2024-01-01T00:00:00",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "total_pages": 1,
        "has_next": False,
        "has_prev": False,
    }

    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=cached_data)

    with patch("bff_service.services.listings_cache.get_listings_cache", return_value=mock_cache):
        from bff_service.services.listings_cache import get_cached_search_results

        result = await get_cached_search_results("python", 1, 20)

    assert result is not None
    assert result.total == 1
    assert result.page == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_get_cached_search_results_miss() -> None:
    """Test getting cached results when cache miss occurs."""
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value=None)

    with patch("bff_service.services.listings_cache.get_listings_cache", return_value=mock_cache):
        from bff_service.services.listings_cache import get_cached_search_results

        result = await get_cached_search_results("python", 1, 20)

    assert result is None


@pytest.mark.asyncio
async def test_get_cached_search_results_invalid_data() -> None:
    """Test getting cached results when cache returns invalid data type."""
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(return_value="invalid string data")

    with patch("bff_service.services.listings_cache.get_listings_cache", return_value=mock_cache):
        from bff_service.services.listings_cache import get_cached_search_results

        result = await get_cached_search_results("python", 1, 20)

    assert result is None


@pytest.mark.asyncio
async def test_get_cached_search_results_redis_error() -> None:
    """Test getting cached results when Redis error occurs."""
    mock_cache = MagicMock()
    mock_cache.get = AsyncMock(side_effect=RedisError("Connection lost"))

    with patch("bff_service.services.listings_cache.get_listings_cache", return_value=mock_cache):
        from bff_service.services.listings_cache import get_cached_search_results

        result = await get_cached_search_results("python", 1, 20)

    assert result is None


@pytest.mark.asyncio
async def test_set_cached_search_results_success(mocker: MockerFixture) -> None:
    """Test setting cached search results successfully."""
    mock_cache = MagicMock()
    mock_cache.set = AsyncMock()

    mocker.patch(
        "bff_service.services.listings_cache.get_settings",
        return_value=SimpleNamespace(caching=SimpleNamespace(search_results_ttl=120)),
    )

    with patch("bff_service.services.listings_cache.get_listings_cache", return_value=mock_cache):
        from bff_service.api.schemas.listings import JobListingResponse
        from bff_service.services.listings_cache import CachedSearchResult, set_cached_search_results

        results = CachedSearchResult(
            items=[
                JobListingResponse(
                    id="1",
                    listing_url="https://example.com/job/1",
                    source="example",
                    title="Job 1",
                    company_name="Company A",
                    description="A test job",
                    location_raw="New York, NY",
                    work_arrangement="remote",
                    seniority_level="junior",
                    language="en",
                    required_skills=["python"],
                    posted_at="2024-01-01T00:00:00",
                    discovered_at="2024-01-01T00:00:00",
                    created_at="2024-01-01T00:00:00",
                )
            ],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
            has_next=False,
            has_prev=False,
        )

        await set_cached_search_results("python", 1, 20, results)

    mock_cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_cached_search_results_redis_error() -> None:
    """Test setting cached search results when Redis error occurs."""
    mock_cache = MagicMock()
    mock_cache.set = AsyncMock(side_effect=RedisError("Connection lost"))

    with patch("bff_service.services.listings_cache.get_listings_cache", return_value=mock_cache):
        from bff_service.api.schemas.listings import JobListingResponse
        from bff_service.services.listings_cache import CachedSearchResult, set_cached_search_results

        results = CachedSearchResult(
            items=[
                JobListingResponse(
                    id="1",
                    listing_url="https://example.com/job/1",
                    source="example",
                    title="Job 1",
                    company_name="Company A",
                    description="A test job",
                    location_raw="New York, NY",
                    work_arrangement="remote",
                    seniority_level="junior",
                    language="en",
                    required_skills=["python"],
                    posted_at="2024-01-01T00:00:00",
                    discovered_at="2024-01-01T00:00:00",
                    created_at="2024-01-01T00:00:00",
                )
            ],
            total=1,
            page=1,
            page_size=20,
            total_pages=1,
            has_next=False,
            has_prev=False,
        )

        # Should not raise exception
        await set_cached_search_results("python", 1, 20, results)


def test_cached_search_result_model() -> None:
    """Test CachedSearchResult model validation."""
    from bff_service.api.schemas.listings import JobListingResponse
    from bff_service.services.listings_cache import CachedSearchResult

    result = CachedSearchResult(
        items=[
            JobListingResponse(
                id="1",
                listing_url="https://example.com/job/1",
                source="example",
                title="Job",
                company_name="Company A",
                description="A test job",
                location_raw="New York, NY",
                work_arrangement="remote",
                seniority_level="junior",
                language="en",
                required_skills=["python"],
                posted_at="2024-01-01T00:00:00",
                discovered_at="2024-01-01T00:00:00",
                created_at="2024-01-01T00:00:00",
            )
        ],
        total=1,
        page=1,
        page_size=20,
        total_pages=1,
        has_next=False,
        has_prev=False,
    )

    assert result.total == 1
    assert result.page == 1
    assert result.page_size == 20
    assert len(result.items) == 1

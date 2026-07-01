"""Listings cache service with Redis caching for FTS search results."""

from __future__ import annotations

import hashlib
import json

from nohiki_observability import get_logger
from nohiki_redis_utils import CacheFactory, RedisCache
from pydantic import BaseModel
from redis.exceptions import RedisError

from bff_service.api.schemas.listings import JobListingResponse
from bff_service.core.config import get_settings

logger = get_logger(__name__)

_CACHE_NAMESPACE = "listings"


def normalize_listing_filter(value: str | None) -> str | None:
    """Normalize a source or company filter exactly once for cache and SQL."""
    if value is None:
        return None
    normalized = value.lower().strip()
    return normalized or None


def get_listings_cache() -> RedisCache:
    """Get or create the listings cache singleton via CacheFactory."""
    settings = get_settings()
    return CacheFactory.create_cache(
        _CACHE_NAMESPACE,
        redis_url=settings.redis.connection_string,
    )


def build_search_cache_key(  # noqa: PLR0913 - cache identity includes every response-shaping input
    query: str,
    page: int,
    page_size: int,
    *,
    source: str | None = None,
    company: str | None = None,
    has_salary: bool | None = None,
    sort: str | None = None,
    direction: str | None = None,
    work_arrangement: str | None = None,
    seniority: str | None = None,
    date_range: str | None = None,
    show_dismissed: bool | None = None,
) -> str:
    """Build a deterministic cache key for a search and every applied filter."""
    normalized_query = query.lower().strip()
    base_key = f"listings:search:{normalized_query}:{page}:{page_size}"
    normalized_source = normalize_listing_filter(source)
    normalized_company = normalize_listing_filter(company)
    normalized_has_salary = True if has_salary else None
    normalized_work_arrangement = normalize_listing_filter(work_arrangement)
    normalized_seniority = normalize_listing_filter(seniority)
    normalized_date_range = date_range or None
    normalized_sort = sort or None
    normalized_direction = direction or None
    normalized_show_dismissed = True if show_dismissed else None
    if all(
        value is None
        for value in (
            normalized_source,
            normalized_company,
            normalized_has_salary,
            normalized_sort,
            normalized_direction,
            normalized_work_arrangement,
            normalized_seniority,
            normalized_date_range,
            normalized_show_dismissed,
        )
    ):
        return base_key
    filters = json.dumps(
        [
            normalized_source,
            normalized_company,
            normalized_has_salary,
            normalized_sort,
            normalized_direction,
            normalized_work_arrangement,
            normalized_seniority,
            normalized_date_range,
            normalized_show_dismissed,
        ],
        separators=(",", ":"),
    )
    digest = hashlib.sha256(filters.encode()).hexdigest()[:16]
    return f"{base_key}:{digest}"


class CachedSearchResult(BaseModel):
    """Typed model for cached search results matching PaginatedResponse shape."""

    items: list[JobListingResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool


async def get_cached_search_results(  # noqa: PLR0913 - mirrors the complete cache identity
    query: str,
    page: int,
    page_size: int,
    *,
    source: str | None = None,
    company: str | None = None,
    has_salary: bool | None = None,
    sort: str | None = None,
    direction: str | None = None,
    work_arrangement: str | None = None,
    seniority: str | None = None,
    date_range: str | None = None,
    show_dismissed: bool | None = None,
) -> CachedSearchResult | None:
    """Get cached search results if available."""
    cache = get_listings_cache()
    key = build_search_cache_key(
        query,
        page,
        page_size,
        source=source,
        company=company,
        has_salary=has_salary,
        sort=sort,
        direction=direction,
        work_arrangement=work_arrangement,
        seniority=seniority,
        date_range=date_range,
        show_dismissed=show_dismissed,
    )

    try:
        result = await cache.get(key)
        if result is None:
            return None
        if not isinstance(result, dict):
            return None
        return CachedSearchResult.model_validate(result)
    except RedisError:
        logger.debug("Cache unavailable for search lookup", exc_info=True)
        return None


async def set_cached_search_results(  # noqa: PLR0913 - mirrors the complete cache identity
    query: str,
    page: int,
    page_size: int,
    results: CachedSearchResult,
    *,
    source: str | None = None,
    company: str | None = None,
    has_salary: bool | None = None,
    sort: str | None = None,
    direction: str | None = None,
    work_arrangement: str | None = None,
    seniority: str | None = None,
    date_range: str | None = None,
    show_dismissed: bool | None = None,
) -> None:
    """Cache search results.

    Silently fails if cache unavailable - search still works from DB.
    """
    cache = get_listings_cache()
    key = build_search_cache_key(
        query,
        page,
        page_size,
        source=source,
        company=company,
        has_salary=has_salary,
        sort=sort,
        direction=direction,
        work_arrangement=work_arrangement,
        seniority=seniority,
        date_range=date_range,
        show_dismissed=show_dismissed,
    )
    settings = get_settings()

    try:
        await cache.set(key, results.model_dump(), ttl=settings.caching.search_results_ttl)
    except RedisError:
        logger.debug("Failed to cache search results", exc_info=True)

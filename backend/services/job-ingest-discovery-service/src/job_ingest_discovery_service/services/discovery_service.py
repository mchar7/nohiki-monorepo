"""Service layer for job discovery orchestration.

Coordinates discovery through pluggable providers, handles deduplication,
and publishes DiscoveredListing events. All parsing happens downstream.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import cast

from nohiki.common.v1 import (
    CountryCode,
    JobBoardSource,
    ListingReference,
    LocationType,
    WorkArrangement,
)
from nohiki.common.v1 import Location as ProtoLocation
from nohiki.job.ingest.v1 import IngestionQuery, ListingDiscovered
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, create_cache, make_cache_key

from job_ingest_discovery_service.core.config import (
    ProviderConfigSettings,
    get_settings,
)
from job_ingest_discovery_service.core.content_hasher import compute_content_hash
from job_ingest_discovery_service.core.kafka import kafka_client
from job_ingest_discovery_service.core.listing_factory import to_discovered_listing
from job_ingest_discovery_service.core.models import (
    DiscoveryLocation,
    DiscoveryRequest,
    DiscoveryResult,
    RawListing,
)
from job_ingest_discovery_service.providers import BaseProvider, ProviderRegistry, get_provider_registry
from job_ingest_discovery_service.providers.base import reset_leaf_fetch_limiter, set_leaf_fetch_limiter
from job_ingest_discovery_service.services.dedup_service import get_dedup_service

logger = get_logger(__name__)

_SUPPORTED_SOURCES: frozenset[JobBoardSource] = frozenset(
    {
        JobBoardSource.INDEED,
        JobBoardSource.LINKEDIN,
        JobBoardSource.GLASSDOOR,
        JobBoardSource.ZIPRECRUITER,
        JobBoardSource.GOOGLE,
    }
)


@lru_cache(maxsize=1)
def _get_cache() -> RedisCache:
    """Get cached Redis client."""
    settings = get_settings()
    return create_cache(settings.service_name, redis_url=settings.redis.connection_string)


def _build_discovery_request(query: IngestionQuery) -> DiscoveryRequest:
    """Convert IngestionQuery proto to DiscoveryRequest."""
    settings = get_settings()

    sources = _filter_sources(list(query.sources))
    if not sources:
        sources = [JobBoardSource.INDEED, JobBoardSource.LINKEDIN]

    locations = tuple(_map_location(loc) for loc in query.locations)
    work_arrangements = tuple(w for w in query.work_arrangements if w != WorkArrangement.UNSPECIFIED)

    requested = query.results_wanted if query.results_wanted > 0 else 50
    results_per_source = min(requested, settings.discovery.max_results_per_source)

    return DiscoveryRequest(
        query_id=query.query_id,
        keywords=tuple(query.search_keywords),
        sources=tuple(sources),
        locations=locations,
        work_arrangements=work_arrangements,
        results_per_source=results_per_source,
        hours_old=query.hours_old if query.hours_old > 0 else None,
    )


def _filter_sources(sources: list[JobBoardSource]) -> list[JobBoardSource]:
    """Filter to supported, non-unspecified sources."""
    return [s for s in sources if s != JobBoardSource.UNSPECIFIED and s in _SUPPORTED_SOURCES]


def _map_location(loc: ProtoLocation) -> DiscoveryLocation:
    """Convert proto Location to DiscoveryLocation."""
    return DiscoveryLocation(
        city=loc.city or None,
        region=loc.state_province or None,
        country=loc.country if loc.country != CountryCode.UNSPECIFIED else CountryCode.UNSPECIFIED,
        is_remote=loc.location_type == LocationType.REMOTE,
    )


async def run_discovery(query: IngestionQuery, discovery_id: str) -> None:
    """Execute job discovery workflow from IngestionQuery event."""
    query_id = query.query_id
    logger.info(
        "Starting discovery", query_id=query_id, discovery_id=discovery_id, keywords=list(query.search_keywords)
    )

    try:
        request = _build_discovery_request(query)
        listings = await _discover_from_all_sources(request)

        if not listings:
            logger.warning("No listings found", query_id=query_id)
            return

        published = await _dedupe_and_publish(listings, query_id, discovery_id)
        logger.info("Discovery completed", query_id=query_id, discovery_id=discovery_id, published=published)

    except Exception:
        logger.exception("Discovery failed", query_id=query_id)
        raise


async def _discover_from_all_sources(request: DiscoveryRequest) -> list[RawListing]:
    """Discover requested sources with one command-wide leaf-fetch limit."""
    registry = get_provider_registry()
    settings = get_settings()
    token = set_leaf_fetch_limiter(asyncio.Semaphore(settings.discovery.max_concurrent))

    async def discover(source: JobBoardSource) -> list[RawListing]:
        try:
            async with asyncio.timeout(settings.discovery.timeout_seconds):
                return await _discover_from_source(registry, request, source)
        except TimeoutError:
            logger.warning("Provider source timed out", query_id=request.query_id, source=source.name)
            return []

    try:
        if len(request.sources) == 1:
            return await discover(request.sources[0])

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(discover(source)) for source in request.sources]
        return [listing for task in tasks for listing in task.result()]
    finally:
        reset_leaf_fetch_limiter(token)


async def _discover_from_source(
    registry: ProviderRegistry,
    request: DiscoveryRequest,
    source: JobBoardSource,
) -> list[RawListing]:
    """Try providers for a source with fallback on failure."""
    providers = registry.get_providers_for_source(source)
    if not providers:
        logger.warning("No providers for source", query_id=request.query_id, source=source.name)
        return []

    single_source_request = _request_for_single_source(request, source)

    for provider in providers:
        result = await _try_provider(provider, single_source_request, source)
        if result is not None:
            return result

    return []


def _request_for_single_source(request: DiscoveryRequest, source: JobBoardSource) -> DiscoveryRequest:
    """Create request targeting single source."""
    return DiscoveryRequest(
        query_id=request.query_id,
        keywords=request.keywords,
        sources=(source,),
        locations=request.locations,
        work_arrangements=request.work_arrangements,
        results_per_source=request.results_per_source,
        hours_old=request.hours_old,
    )


async def _try_provider(
    provider: BaseProvider,
    request: DiscoveryRequest,
    source: JobBoardSource,
) -> list[RawListing] | None:
    """Execute provider and handle success/failure. Returns None to signal fallback."""
    config = _get_provider_config(provider)

    logger.info("Executing provider", provider=provider.name, query_id=request.query_id, source=source.name)
    result = await provider.discover(request)

    if not result.error:
        await _clear_fallback_state(provider.name, source)
        logger.info(
            "Provider completed",
            provider=provider.name,
            query_id=request.query_id,
            count=len(result.listings),
            duration=round(result.duration_seconds, 2),
        )
        return result.listings

    logger.warning("Provider failed", provider=provider.name, query_id=request.query_id, error=result.error)

    if await _should_fallback(provider.name, source, result, config):
        return None
    return []


@lru_cache(maxsize=32)
def _get_provider_config_map() -> dict[str, ProviderConfigSettings]:
    """Get cached provider config map."""
    settings = get_settings()
    return {cfg.name: cfg for cfg in settings.provider_registry.providers}


def _get_provider_config(provider: BaseProvider) -> ProviderConfigSettings:
    """Get effective config for provider (from settings or defaults)."""
    config_map = _get_provider_config_map()
    if provider.name in config_map:
        return config_map[provider.name]

    return ProviderConfigSettings(
        name=provider.name,
        enabled=provider.default_enabled(),
        priority=provider.default_priority(),
        fallback=provider.default_fallback_settings(),
    )


def _make_fallback_key(provider_name: str, source: JobBoardSource) -> str:
    """Build Redis key for fallback state."""
    return make_cache_key("provider_fallback", provider_name, source.name)


async def _clear_fallback_state(provider_name: str, source: JobBoardSource) -> None:
    """Clear fallback state on success."""
    cache = _get_cache()
    await cache.delete(_make_fallback_key(provider_name, source))


async def _should_fallback(
    provider_name: str,
    source: JobBoardSource,
    result: DiscoveryResult,
    config: ProviderConfigSettings,
) -> bool:
    """Determine if we should fallback to next provider."""
    if not config.fallback.enabled:
        return False

    if result.error_code == "rate_limited" and result.retry_after_seconds is not None:
        return result.retry_after_seconds > config.fallback.rate_limit_wait_threshold_seconds

    consecutive, duration = await _record_error(provider_name, source)
    return (
        consecutive >= config.fallback.min_consecutive_errors
        and duration >= config.fallback.error_duration_threshold_seconds
    )


async def _record_error(provider_name: str, source: JobBoardSource) -> tuple[int, float]:
    """Record error and return (consecutive_count, duration_since_first)."""
    now = time.time()
    key = _make_fallback_key(provider_name, source)
    cache = _get_cache()
    settings = get_settings()

    raw_state = await cache.get(key)

    first_at = now
    consecutive = 0
    if isinstance(raw_state, dict):
        state = cast("dict[str, object]", raw_state)
        raw_first = state.get("first_error_at")
        if isinstance(raw_first, (int, float)):
            first_at = float(raw_first)
        raw_consec = state.get("consecutive_errors")
        if isinstance(raw_consec, (int, float)):
            consecutive = int(raw_consec)

    if consecutive == 0:
        first_at = now

    await cache.set(
        key,
        {"first_error_at": first_at, "last_error_at": now, "consecutive_errors": consecutive + 1},
        ttl=settings.caching.ttls.fallback_state,
    )

    return consecutive + 1, now - first_at


def _compute_listing_hash(listing: RawListing) -> str:
    """Compute content hash for a listing using centralized hasher."""
    return compute_content_hash(listing.title, listing.company, listing.description)


async def _dedupe_and_publish(listings: list[RawListing], query_id: str, discovery_id: str) -> int:
    """Publish novel listings concurrently, then mark successful deliveries as seen."""
    dedup = get_dedup_service()
    to_publish: list[tuple[RawListing, str, str]] = []
    pending_keys: set[str] = set()

    for listing in listings:
        content_hash = _compute_listing_hash(listing)
        dedup_key = f"{query_id}:{content_hash}"
        if dedup_key in pending_keys or await dedup.is_duplicate(dedup_key):
            logger.debug("Duplicate skipped", url=listing.listing_url, hash=content_hash[:16])
            continue
        pending_keys.add(dedup_key)
        to_publish.append((listing, content_hash, dedup_key))

    failures: list[Exception] = []

    async def publish_and_mark(listing: RawListing, content_hash: str, dedup_key: str) -> None:
        try:
            await _publish_listing(listing, content_hash, query_id, discovery_id)
            await dedup.mark_seen(dedup_key)
        except Exception as error:
            logger.exception("Failed to deliver listing", url=listing.listing_url, query_id=query_id)
            failures.append(error)

    async with asyncio.TaskGroup() as tg:
        for listing, content_hash, dedup_key in to_publish:
            tg.create_task(publish_and_mark(listing, content_hash, dedup_key))

    if failures:
        raise failures[0]
    return len(to_publish)


async def _publish_listing(listing: RawListing, content_hash: str, query_id: str, discovery_id: str) -> None:
    """Publish a single listing event."""
    settings = get_settings()
    now = datetime.now(UTC)
    discovered = to_discovered_listing(listing, now)

    await kafka_client.publish(
        topic=Topics.JOB_INGEST_LISTING_DISCOVERED,
        key=f"{query_id}:{content_hash[:16]}",
        message=ListingDiscovered(
            metadata=create_event_metadata(settings.service_name, discovery_id),
            query_id=query_id,
            listing=ListingReference(
                listing_url=discovered.listing_url,
                external_listing_id=discovered.external_id or "",
                source=discovered.source,
            ),
            discovered_data=discovered,
            discovered_at=now,
        ),
    )

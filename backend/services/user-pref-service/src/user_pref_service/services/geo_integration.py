"""Geocoding integration for user-pref-service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import cache
from typing import TYPE_CHECKING

from nohiki.common.v1 import Location
from nohiki_geo_utils import create_cached_geocoder
from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, create_cache

from user_pref_service.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = get_logger(__name__)


@cache
def _get_cached_geocoder() -> Callable[[Location], Awaitable[Location]]:
    """Get or create a cached geocoder singleton.

    Returns:
        Async callable that geocodes a single Location.

    """
    settings = get_settings()

    def cache_factory() -> RedisCache:
        return create_cache(settings.service_name, redis_url=settings.redis.connection_string)

    _, cached_geocode = create_cached_geocoder(cache_factory)
    return cached_geocode


async def geocode_locations(locations: list[Location]) -> list[Location]:
    """Geocode locations using nohiki-geo-utils with infrastructure injection.

    Args:
        locations: Physical locations to geocode.

    Returns:
        Locations with coordinates populated where geocoding succeeded.

    """
    if not locations:
        return []

    cached_geocode = _get_cached_geocoder()

    async def _safe_geocode(location: Location) -> Location:
        try:
            return await cached_geocode(location)
        except Exception:  # noqa: BLE001  # TaskGroup cancels ALL tasks on unhandled exception
            logger.debug("Geocoding failed, keeping original", city=location.city, exc_info=True)
            return location

    if len(locations) == 1:
        return [await _safe_geocode(locations[0])]

    results: list[Location] = [Location()] * len(locations)
    async with asyncio.TaskGroup() as tg:
        for i, loc in enumerate(locations):

            async def _geocode_at(idx: int, location: Location) -> None:
                results[idx] = await _safe_geocode(location)

            tg.create_task(_geocode_at(i, loc))

    return results

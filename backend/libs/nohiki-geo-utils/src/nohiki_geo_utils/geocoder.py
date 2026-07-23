"""Redis-cached geocoding using GeoPy Nominatim."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Final

from geopy.adapters import AioHTTPAdapter
from nohiki.common.v1 import CountryCode, GeoCoordinates, Location

if TYPE_CHECKING:
    from geopy.geocoders import Nominatim
    from nohiki_redis_utils import RedisCache

logger = logging.getLogger(__name__)

MIN_QUERY_LENGTH: Final[int] = 3
MAX_QUERY_LENGTH: Final[int] = 512


def _geocode_cache_key(
    prefix: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> str:
    """Build a deterministic cache key without storing location text in Redis."""
    query = args[0] if args else kwargs.get("query", "")
    digest = hashlib.sha256(str(query).strip().encode()).hexdigest()
    return f"{prefix}:{digest}"


COUNTRY_CODE_NAMES: dict[CountryCode, str] = {
    CountryCode.USA: "United States",
    CountryCode.CAN: "Canada",
    CountryCode.GBR: "United Kingdom",
    CountryCode.DEU: "Germany",
    CountryCode.FRA: "France",
    CountryCode.AUS: "Australia",
    CountryCode.IND: "India",
    CountryCode.NLD: "Netherlands",
    CountryCode.CHE: "Switzerland",
    CountryCode.IRL: "Ireland",
    CountryCode.NZL: "New Zealand",
    CountryCode.SGP: "Singapore",
    CountryCode.ISR: "Israel",
    CountryCode.ARE: "United Arab Emirates",
}


def build_geocode_query(location: Location) -> str:
    """Build geocoding query string from Location proto.

    Args:
        location: Location proto object

    Returns:
        Query string like "New York, NY, United States"

    """
    parts: list[str] = []

    if location.city:
        parts.append(location.city)

    if location.state_province:
        parts.append(location.state_province)

    if country_name := COUNTRY_CODE_NAMES.get(location.country):
        parts.append(country_name)

    return ", ".join(parts)


def _create_geocoder() -> Nominatim:
    """Create a new Nominatim geocoder instance.

    Each instance should be used as an async context manager
    to ensure the underlying aiohttp session is properly closed.
    """
    from geopy.geocoders import Nominatim  # noqa: PLC0415 -- Load GeoPy on first geocode.

    return Nominatim(
        user_agent="nohiki-job-platform/1.0",
        adapter_factory=AioHTTPAdapter,
    )


async def geocode_query(query: str) -> GeoCoordinates | None:
    """Geocode a query string to coordinates (uncached).

    For cached version, use create_cached_geocoder().

    Args:
        query: Address string (e.g., "New York, NY, United States")

    Returns:
        GeoCoordinates if found, None otherwise

    """
    query = query.strip()
    if len(query) < MIN_QUERY_LENGTH or len(query) > MAX_QUERY_LENGTH:
        return None
    from geopy.exc import (  # noqa: PLC0415 -- Load GeoPy on first geocode.
        GeocoderServiceError,
        GeocoderTimedOut,
        GeocoderUnavailable,
    )

    async with _create_geocoder() as geocoder:
        try:
            result = await geocoder.geocode(query, timeout=10)
            if result:
                return GeoCoordinates(
                    latitude=result.latitude,
                    longitude=result.longitude,
                )
        except GeocoderTimedOut, GeocoderServiceError, GeocoderUnavailable, TimeoutError:
            logger.debug("Geocoding request failed", exc_info=True)

    return None


async def geocode_location(location: Location) -> Location:
    """Geocode a Location proto object (uncached).

    If the location already has coordinates, returns unchanged.
    Otherwise, attempts to geocode and returns a new Location
    with coordinates populated.

    For cached version, use create_cached_geocoder().

    Args:
        location: Location proto object

    Returns:
        Location with coordinates field populated (if geocoding succeeded)

    """
    if location.coordinates is not None:
        return location

    query = build_geocode_query(location)
    if not query:
        return location

    coordinates = await geocode_query(query)

    if coordinates is None:
        return location

    return Location(
        city=location.city,
        state_province=location.state_province,
        country=location.country,
        location_type=location.location_type,
        coordinates=coordinates,
    )


type CachedGeocoder = tuple[
    Callable[[str], Awaitable[GeoCoordinates | None]],
    Callable[[Location], Awaitable[Location]],
]


def create_cached_geocoder(
    cache_factory: Callable[[], RedisCache],
    *,
    cache_ttl: int = 604800,
    rate_limit_requests: int = 50,
    rate_limit_window: int = 60,
) -> CachedGeocoder:
    """Create Redis-cached geocoding functions.

    Returns a tuple of (cached_geocode_query, cached_geocode_location).

    Args:
        cache_factory: Factory to obtain a RedisCache instance
        cache_ttl: Cache TTL in seconds (default: 7 days)
        rate_limit_requests: Max requests per window (default: 50)
        rate_limit_window: Rate limit window in seconds (default: 60)

    Returns:
        Tuple of cached geocoding functions

    Example:
        from nohiki_redis_utils import create_cache

        cache_factory = lambda: create_cache(settings.redis)
        cached_query, cached_location = create_cached_geocoder(cache_factory)

        coords = await cached_query("New York, NY")
        location = await cached_location(location_proto)

    """
    from nohiki_redis_utils import cached  # noqa: PLC0415 -- Load Redis support on cached geocoder creation.
    from nohiki_redis_utils.rate_limit_decorator import (  # noqa: PLC0415 -- Load Redis support on demand.
        rate_limited,
    )

    @cached(
        key_prefix="geo:query",
        ttl=cache_ttl,
        cache_factory=cache_factory,
        key_builder=_geocode_cache_key,
    )
    @rate_limited(
        requests=rate_limit_requests,
        window_seconds=rate_limit_window,
        cache_factory=cache_factory,
        raise_on_limit=False,
    )
    async def _cached_geocode_query(query: str) -> GeoCoordinates | None:
        return await geocode_query(query)

    async def _cached_geocode_location(location: Location) -> Location:
        if location.coordinates is not None:
            return location

        query = build_geocode_query(location)
        if not query:
            return location

        coordinates = await _cached_geocode_query(query)

        if coordinates is None:
            return location

        return Location(
            city=location.city,
            state_province=location.state_province,
            country=location.country,
            location_type=location.location_type,
            coordinates=coordinates,
        )

    return (_cached_geocode_query, _cached_geocode_location)

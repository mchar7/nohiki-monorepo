# Nohiki Geo Utils

Resolves location strings to geographic coordinates via GeoPy's Nominatim geocoder, and
calculates geodesic distances between `Location` proto objects. Three services depend on
it: `job-ingest-enrichment-service` geocodes job locations during LLM extraction,
`user-pref-service` geocodes user-declared preferred locations, and
`job-correlation-evaluation-service` uses the distance utilities to produce location
features for deterministic fit ranking.

## Quick Start

```python
from nohiki_geo_utils import create_cached_geocoder
from nohiki_redis_utils import RedisCache, create_cache

# Wire up once (e.g., in service startup or a lazy singleton)
def cache_factory() -> RedisCache:
    return create_cache(settings.service_name, redis_url=settings.redis.connection_string)

cached_query, cached_location = create_cached_geocoder(cache_factory)

# Geocode a raw query string → GeoCoordinates | None
coords = await cached_query("San Francisco, CA, United States")

# Geocode a Location proto (returns Location with coordinates populated)
from nohiki.common.v1 import CountryCode, Location, LocationType

loc = Location(city="Toronto", state_province="Ontario", country=CountryCode.CAN,
               location_type=LocationType.PHYSICAL)
geocoded = await cached_location(loc)
# geocoded.coordinates.latitude, geocoded.coordinates.longitude now set
```

For distance calculation (no Redis required):

```python
from nohiki_geo_utils import calculate_distance

result = calculate_distance(job_location, user_location)
if result:
    print(result.distance_km, result.is_same_city, result.confidence)
```

## Core Concepts

### Cached vs. uncached geocoding

The library exposes two levels of geocoding:

- **Uncached** (`geocode_query`, `geocode_location`) -- call Nominatim directly, no Redis
  dependency. Suitable for one-off scripts or tests, but will hit Nominatim on every call.
- **Cached** (`create_cached_geocoder`) -- factory that returns a `(cached_query, cached_location)`
  tuple. Both functions layer Redis caching (7-day TTL, key prefix `geo:query`) and a
  sliding-window rate limiter (50 requests per 60 seconds by default) on top of the same
  uncached functions. All three services use this path in production.

The `create_cached_geocoder` factory takes a `cache_factory: Callable[[], RedisCache]`
rather than a `RedisCache` instance directly, matching the `nohiki-redis-utils`
dependency-injection pattern used throughout the monorepo.

### Location proto handling

`geocode_location` / `cached_location` accept and return `nohiki.common.v1.Location` protos.
If the proto already has a `coordinates` field set, both functions return it unchanged --
no Nominatim call is made. When geocoding succeeds, a new `Location` is returned with
all original fields preserved and `coordinates` populated as a `GeoCoordinates` proto
(`latitude`, `longitude`). When geocoding fails (Nominatim unavailable, no result, or
query too short), the original `Location` is returned unchanged with `coordinates` still
`None`.

### Query building

`build_geocode_query(location: Location) -> str` assembles a human-readable query string
from a `Location` proto, for example, `"New York, NY, United States"` from
`city="New York", state_province="NY", country=CountryCode.USA`. Country codes are mapped
to full English names via `COUNTRY_CODE_NAMES`. Unknown or `UNSPECIFIED` country codes are
omitted. The function handles partial locations gracefully; `Location()` returns `""`, which
both `geocode_query` and `geocode_location` treat as a no-op.

### Rate limiting

`create_cached_geocoder` decorates the underlying Nominatim call with
`@rate_limited` from `nohiki-redis-utils`. The defaults (50 requests / 60 seconds,
`raise_on_limit=False`) implement a conservative sliding-window budget across all service
instances using Redis as a shared counter. When the limit is reached, the call returns
`None` silently rather than raising; the service treats it the same as a geocoding miss.
The raw Nominatim client uses `user_agent="nohiki-job-platform/1.0"` to satisfy
Nominatim's terms of service.

### Distance calculation

`calculate_distance(loc1, loc2) -> DistanceResult | None` computes the geodesic
(great-circle) distance between two `Location` protos using geopy's `geodesic`. It returns
`None` if either location is `None` or missing coordinates. The returned `DistanceResult`
includes `distance_km`, `distance_miles`, boolean same-city/state/country flags, and a
`confidence` score derived from the precision field of each location.

The `confidence` field reflects location precision using `PRECISION_CONFIDENCE`:

| Precision enum value | Confidence |
| --- | --- |
| `EXACT_ADDRESS` (1) | 1.0 |
| `NEIGHBORHOOD` (2) | 0.9 |
| `CITY_CENTER` (3) | 0.6 |
| `REGION_CENTER` (4) | 0.3 |
| `COUNTRY_CENTER` (5) | 0.1 |
| `UNSPECIFIED` (0) | 0.5 |

The final confidence is `min(job_precision_confidence, user_precision_confidence)`.
Repeated distance calculations between the same coordinate pairs are memoized with
`@lru_cache(maxsize=4096)` -- geocoding is the expensive step, not the distance math.

### GeodesicEstimator

`GeodesicEstimator` implements the `DistanceEstimator` protocol. It wraps the same cached
geodesic calculation and returns an `EstimationResult` with `distance_km`, `confidence`,
and `method="geodesic"`. The `duration_minutes` and `transit_mode_used` fields are always
`None` -- they exist for a future commute-time estimator that would use a real travel API.
`GeodesicEstimator.estimate()` raises `ValueError` if either location lacks coordinates;
callers should geocode locations before calling it.

## API Reference

### Geocoding

- **`geocode_query(query: str) -> GeoCoordinates | None`** -- Geocodes a raw query string.
  Returns `None` for queries shorter than 3 characters, empty strings, and any Nominatim
  error (`GeocoderTimedOut`, `GeocoderServiceError`, `GeocoderUnavailable`, `TimeoutError`).
  Errors are logged at DEBUG level; no exception propagates to the caller.

- **`geocode_location(location: Location) -> Location`** -- Geocodes a `Location` proto.
  Returns the original location unchanged if coordinates are already set or if the query
  string is empty. Delegates to `geocode_query` internally.

- **`create_cached_geocoder(cache_factory, *, cache_ttl, rate_limit_requests, rate_limit_window) -> CachedGeocoder`** --
  Factory that returns `(cached_query_fn, cached_location_fn)`. Cache TTL defaults to
  7 days (604800 s). Rate limit defaults: 50 requests per 60-second window.
  All three keyword arguments are configurable. See [Configuration](#configuration) for defaults.

- **`build_geocode_query(location: Location) -> str`** -- Builds a Nominatim query string
  from a `Location` proto. Returns `""` if all fields are absent.

- **`COUNTRY_CODE_NAMES: dict[CountryCode, str]`** -- Maps `CountryCode` enum values to
  English country names for 14 supported countries (USA, CAN, GBR, DEU, FRA, AUS, IND,
  NLD, CHE, IRL, NZL, SGP, ISR, ARE).

### Distance

- **`calculate_distance(loc1: Location | None, loc2: Location | None) -> DistanceResult | None`** --
  Geodesic distance between two locations. Returns `None` if either argument is `None` or
  missing `coordinates`.

- **`DistanceResult`** -- Frozen dataclass: `distance_km`, `distance_miles`, `is_same_city`,
  `is_same_state`, `is_same_country`, `confidence`, `job_precision`, `user_precision`.

- **`GeodesicEstimator`** -- Implements `DistanceEstimator`. `estimate(origin, destination) -> EstimationResult`.
  Raises `ValueError` if coordinates are absent.

- **`EstimationResult`** -- Frozen dataclass: `distance_km`, `duration_minutes` (always `None`),
  `confidence`, `method` (`"geodesic"`), `transit_mode_used` (always `None`).

- **`PRECISION_CONFIDENCE: dict[int, float]`** -- Maps location precision integers to
  confidence weights used in distance scoring.

## Configuration

`create_cached_geocoder` accepts keyword arguments to override defaults:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `cache_ttl` | `604800` (7 days) | Redis TTL in seconds for geocode results |
| `rate_limit_requests` | `50` | Max Nominatim calls per window |
| `rate_limit_window` | `60` | Window duration in seconds |

There are no environment variables. Configuration is passed at construction time.
The `redis` extra must be installed for caching to work:

```toml
dependencies = [
    "nohiki-geo-utils[redis]==0.1.0",
]
```

Without the `redis` extra, `create_cached_geocoder` is still importable but will fail at
runtime when `nohiki_redis_utils` is not available. The uncached functions (`geocode_query`,
`geocode_location`, `calculate_distance`) work without the extra.

## Testing

Patch `nohiki_geo_utils.geocoder._create_geocoder` to avoid real Nominatim calls in unit
tests:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from nohiki_geo_utils import geocode_query

mock_result = MagicMock()
mock_result.latitude = 40.7128
mock_result.longitude = -74.0060

mock_geocoder = AsyncMock()
mock_geocoder.geocode = AsyncMock(return_value=mock_result)
mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
mock_geocoder.__aexit__ = AsyncMock(return_value=False)

with patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder):
    coords = await geocode_query("New York, NY, United States")
    assert coords.latitude == pytest.approx(40.7128)
```

For `create_cached_geocoder`, also patch the rate limiter to prevent Redis calls:

```python
with (
    patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder),
    patch("nohiki_redis_utils.rate_limit_decorator.create_rate_limiter") as mock_limiter,
):
    mock_limiter_instance = MagicMock()
    mock_limiter_instance.check = AsyncMock(return_value=MagicMock(allowed=True, retry_after=None))
    mock_limiter.return_value = mock_limiter_instance
    ...
```

Integration tests in `tests/test_geocoder_integration.py` make real Nominatim calls and
are marked `@pytest.mark.integration`. Run them with:

```bash
uv run --package nohiki-geo-utils pytest backend/libs/nohiki-geo-utils/tests/test_geocoder_integration.py -v --tb=short
```

The integration suite enforces a 1.5-second delay between requests via `asyncio.sleep` to
stay within Nominatim's usage policy.

## Design Decisions

**Why factory injection for `RedisCache`?** Services in this monorepo create `RedisCache`
instances lazily (after settings are loaded). Passing a `cache_factory: Callable[[], RedisCache]`
rather than an instance lets `create_cached_geocoder` be called at module level without
requiring Redis to be available at import time.

**Why `raise_on_limit=False`?** Geocoding is a best-effort enrichment step. Failing to
geocode a location degrades match quality slightly; it never blocks the pipeline. Silently
returning `None` on rate limit lets the Kafka handler continue processing rather than
triggering a retry and consuming another rate-limit slot.

**Why 7-day cache TTL?** City coordinates do not change. Caching aggressively reduces
Nominatim load and keeps the service well within the usage policy during backfill runs
where thousands of job listings may share the same city string.

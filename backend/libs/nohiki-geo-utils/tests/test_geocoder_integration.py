"""Integration tests for geocoder with real Nominatim API calls.

These tests make REAL HTTP requests to the public Nominatim geocoding API.
They verify actual geocoding results and assert coordinate accuracy with tolerance.

IMPORTANT: These tests respect Nominatim's usage policy:
- 1 request per second maximum (enforced via asyncio.sleep between API calls)
- Proper user agent identification
- No bulk geocoding

Run with: uv run pytest tests/test_geocoder_integration.py -v --tb=short
"""

from __future__ import annotations

import asyncio

import pytest
from nohiki.common.v1 import CountryCode, GeoCoordinates, Location, LocationType
from nohiki_geo_utils.geocoder import (
    build_geocode_query,
    geocode_location,
    geocode_query,
)

COORDINATE_TOLERANCE = 0.05
RATE_LIMIT_DELAY = 1.5

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="module"),
]


class TestRealGeocodeQuery:
    """Integration tests for geocode_query with real Nominatim API."""

    async def test_geocode_major_cities(self) -> None:
        """Test geocoding major cities returns accurate coordinates."""
        test_cases = [
            ("New York, NY, United States", 40.7128, -74.0060),
            ("London, United Kingdom", 51.5074, -0.1278),
            ("Toronto, Ontario, Canada", 43.6532, -79.3832),
        ]

        for query, expected_lat, expected_lon in test_cases:
            result = await geocode_query(query)

            assert result is not None, f"Failed to geocode: {query}"
            assert result.latitude == pytest.approx(expected_lat, abs=COORDINATE_TOLERANCE), (
                f"Latitude mismatch for {query}"
            )
            assert result.longitude == pytest.approx(expected_lon, abs=COORDINATE_TOLERANCE), (
                f"Longitude mismatch for {query}"
            )

            await asyncio.sleep(RATE_LIMIT_DELAY)

    async def test_geocode_international_cities(self) -> None:
        """Test geocoding international cities returns accurate coordinates."""
        await asyncio.sleep(RATE_LIMIT_DELAY)

        test_cases = [
            ("Tokyo, Japan", 35.6764, 139.7640),
            ("Sydney, Australia", -33.8688, 151.2093),
            ("Berlin, Germany", 52.5170, 13.3889),
        ]

        for query, expected_lat, expected_lon in test_cases:
            result = await geocode_query(query)

            assert result is not None, f"Failed to geocode: {query}"
            assert result.latitude == pytest.approx(expected_lat, abs=COORDINATE_TOLERANCE), (
                f"Latitude mismatch for {query}"
            )
            assert result.longitude == pytest.approx(expected_lon, abs=COORDINATE_TOLERANCE), (
                f"Longitude mismatch for {query}"
            )

            await asyncio.sleep(RATE_LIMIT_DELAY)


class TestRealGeocodeLocation:
    """Integration tests for geocode_location with real Nominatim API."""

    async def test_geocode_location_protos(self) -> None:
        """Test geocoding Location proto objects."""
        await asyncio.sleep(RATE_LIMIT_DELAY)

        test_cases = [
            (
                Location(
                    city="San Francisco",
                    state_province="California",
                    country=CountryCode.USA,
                    location_type=LocationType.PHYSICAL,
                ),
                37.7749,
                -122.4194,
            ),
            (
                Location(
                    city="Amsterdam",
                    country=CountryCode.NLD,
                    location_type=LocationType.PHYSICAL,
                ),
                52.3676,
                4.9041,
            ),
            (
                Location(
                    city="Dublin",
                    country=CountryCode.IRL,
                    location_type=LocationType.PHYSICAL,
                ),
                53.3498,
                -6.2603,
            ),
        ]

        for location, expected_lat, expected_lon in test_cases:
            result = await geocode_location(location)

            assert result.coordinates is not None, f"Failed to geocode: {location.city}"
            assert result.coordinates.latitude == pytest.approx(expected_lat, abs=COORDINATE_TOLERANCE)
            assert result.coordinates.longitude == pytest.approx(expected_lon, abs=COORDINATE_TOLERANCE)
            assert result.city == location.city
            assert result.country == location.country

            await asyncio.sleep(RATE_LIMIT_DELAY)

    async def test_location_preserves_existing_coordinates(self) -> None:
        """Test that locations with existing coordinates are unchanged."""
        original_coords = GeoCoordinates(latitude=40.0, longitude=-74.0)
        location = Location(
            city="Test City",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=original_coords,
        )

        result = await geocode_location(location)

        assert result.coordinates is not None
        assert result.coordinates.latitude == pytest.approx(40.0, abs=0.001)
        assert result.coordinates.longitude == pytest.approx(-74.0, abs=0.001)


class TestBuildGeocodeQueryIntegration:
    """Integration tests verifying query building produces geocodable strings."""

    async def test_built_query_is_geocodable(self) -> None:
        """Test that built query string can be geocoded successfully."""
        await asyncio.sleep(RATE_LIMIT_DELAY)

        location = Location(
            city="Seattle",
            state_province="Washington",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )

        query = build_geocode_query(location)
        assert query == "Seattle, Washington, United States"

        result = await geocode_query(query)

        assert result is not None
        assert result.latitude == pytest.approx(47.6062, abs=COORDINATE_TOLERANCE)
        assert result.longitude == pytest.approx(-122.3321, abs=COORDINATE_TOLERANCE)

    async def test_city_country_only_is_geocodable(self) -> None:
        """Test that city+country query can be geocoded."""
        await asyncio.sleep(RATE_LIMIT_DELAY)

        location = Location(
            city="Paris",
            country=CountryCode.FRA,
            location_type=LocationType.PHYSICAL,
        )

        query = build_geocode_query(location)
        assert query == "Paris, France"

        result = await geocode_query(query)

        assert result is not None
        assert result.latitude == pytest.approx(48.8566, abs=COORDINATE_TOLERANCE)
        assert result.longitude == pytest.approx(2.3522, abs=COORDINATE_TOLERANCE)


class TestEdgeCasesIntegration:
    """Integration tests for edge cases with real API."""

    async def test_nonexistent_location_returns_none(self) -> None:
        """Test that truly nonexistent locations return None."""
        await asyncio.sleep(RATE_LIMIT_DELAY)

        result = await geocode_query("Xyzzy Nonexistent Place 12345")
        assert result is None

    async def test_ambiguous_city_still_geocodes(self) -> None:
        """Test that ambiguous city names still return a result."""
        await asyncio.sleep(RATE_LIMIT_DELAY)

        result = await geocode_query("Springfield, United States")
        assert result is not None
        assert -90 <= result.latitude <= 90
        assert -180 <= result.longitude <= 180

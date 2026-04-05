"""Tests for geocoder module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.common.v1 import CountryCode, GeoCoordinates, Location, LocationType
from nohiki_geo_utils.geocoder import (
    COUNTRY_CODE_NAMES,
    MIN_QUERY_LENGTH,
    build_geocode_query,
    geocode_location,
    geocode_query,
)


class TestBuildGeocodeQuery:
    """Tests for build_geocode_query function."""

    def test_full_location(self) -> None:
        """Test with city, state, and country."""
        location = Location(
            city="New York",
            state_province="NY",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        result = build_geocode_query(location)
        assert result == "New York, NY, United States"

    def test_city_and_country_only(self) -> None:
        """Test with city and country, no state."""
        location = Location(
            city="London",
            country=CountryCode.GBR,
            location_type=LocationType.PHYSICAL,
        )
        result = build_geocode_query(location)
        assert result == "London, United Kingdom"

    def test_unknown_country(self) -> None:
        """Test with unknown country code."""
        location = Location(
            city="Test City",
            country=CountryCode.UNSPECIFIED,
            location_type=LocationType.PHYSICAL,
        )
        result = build_geocode_query(location)
        assert result == "Test City"

    def test_empty_location(self) -> None:
        """Test with empty location."""
        location = Location()
        result = build_geocode_query(location)
        assert result == ""

    def test_state_only(self) -> None:
        """Test with only state and country."""
        location = Location(
            state_province="California",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        result = build_geocode_query(location)
        assert result == "California, United States"

    def test_canadian_location(self) -> None:
        """Test with Canadian location."""
        location = Location(
            city="Toronto",
            state_province="Ontario",
            country=CountryCode.CAN,
            location_type=LocationType.PHYSICAL,
        )
        result = build_geocode_query(location)
        assert result == "Toronto, Ontario, Canada"


class TestCountryCodeNames:
    """Tests for country code mapping."""

    def test_major_countries_present(self) -> None:
        """Verify major countries are in mapping."""
        assert CountryCode.USA in COUNTRY_CODE_NAMES
        assert CountryCode.CAN in COUNTRY_CODE_NAMES
        assert CountryCode.GBR in COUNTRY_CODE_NAMES
        assert CountryCode.DEU in COUNTRY_CODE_NAMES
        assert CountryCode.FRA in COUNTRY_CODE_NAMES
        assert CountryCode.AUS in COUNTRY_CODE_NAMES

    def test_unspecified_not_present(self) -> None:
        """Verify UNSPECIFIED is not in mapping."""
        assert CountryCode.UNSPECIFIED not in COUNTRY_CODE_NAMES

    def test_all_mapped_countries_have_names(self) -> None:
        """Verify all mapped countries have non-empty names."""
        for country, name in COUNTRY_CODE_NAMES.items():
            assert name, f"Country {country} has empty name"
            assert isinstance(name, str)


class TestGeocodeQuery:
    """Tests for geocode_query function."""

    async def test_empty_query_returns_none(self) -> None:
        """Test that empty query returns None."""
        result = await geocode_query("")
        assert result is None

    async def test_short_query_returns_none(self) -> None:
        """Test that very short query returns None."""
        result = await geocode_query("AB")
        assert result is None
        assert len("AB") < MIN_QUERY_LENGTH

    async def test_successful_geocode(self) -> None:
        """Test successful geocoding with mocked response."""
        mock_result = MagicMock()
        mock_result.latitude = 40.7128
        mock_result.longitude = -74.0060

        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(return_value=mock_result)
        mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
        mock_geocoder.__aexit__ = AsyncMock(return_value=False)

        with patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder):
            result = await geocode_query("New York, NY, United States")

            assert result is not None
            assert result.latitude == pytest.approx(40.7128)
            assert result.longitude == pytest.approx(-74.0060)

    async def test_geocode_returns_none_on_no_result(self) -> None:
        """Test geocoding returns None when no result found."""
        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(return_value=None)
        mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
        mock_geocoder.__aexit__ = AsyncMock(return_value=False)

        with patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder):
            result = await geocode_query("Nonexistent Place XYZ123")
            assert result is None

    async def test_geocode_handles_exception(self) -> None:
        """Test geocoding handles exceptions gracefully."""
        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(side_effect=TimeoutError("Connection timeout"))
        mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
        mock_geocoder.__aexit__ = AsyncMock(return_value=False)

        with patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder):
            result = await geocode_query("New York, NY")
            assert result is None


class TestGeocodeLocation:
    """Tests for geocode_location function."""

    async def test_already_geocoded_returns_unchanged(self) -> None:
        """Test that location with coordinates is returned unchanged."""
        location = Location(
            city="New York",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=40.7128, longitude=-74.0060),
        )
        result = await geocode_location(location)
        assert result.coordinates is not None
        assert result.coordinates.latitude == pytest.approx(40.7128)

    async def test_empty_location_returns_unchanged(self) -> None:
        """Test that empty location returns unchanged."""
        location = Location()
        result = await geocode_location(location)
        assert result.coordinates is None

    async def test_successful_geocode_adds_coordinates(self) -> None:
        """Test successful geocoding adds coordinates."""
        location = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )

        mock_result = MagicMock()
        mock_result.latitude = 37.7749
        mock_result.longitude = -122.4194

        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(return_value=mock_result)
        mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
        mock_geocoder.__aexit__ = AsyncMock(return_value=False)

        with patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder):
            result = await geocode_location(location)

            assert result.coordinates is not None
            assert result.coordinates.latitude == pytest.approx(37.7749)
            assert result.coordinates.longitude == pytest.approx(-122.4194)
            assert result.city == "San Francisco"
            assert result.country == CountryCode.USA

    async def test_failed_geocode_returns_original(self) -> None:
        """Test that failed geocoding returns original location."""
        location = Location(
            city="Unknown City",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )

        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(return_value=None)
        mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
        mock_geocoder.__aexit__ = AsyncMock(return_value=False)

        with patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder):
            result = await geocode_location(location)

            assert result.coordinates is None
            assert result.city == "Unknown City"


class TestCachedGeocoder:
    """Tests for create_cached_geocoder factory."""

    def test_create_cached_geocoder_returns_tuple(self) -> None:
        """Test that factory returns tuple of functions."""
        from nohiki_geo_utils import create_cached_geocoder

        mock_cache = MagicMock()

        def cache_factory() -> MagicMock:
            return mock_cache

        result = create_cached_geocoder(cache_factory)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert callable(result[0])
        assert callable(result[1])

    async def test_cached_geocode_query_calls_underlying(self) -> None:
        """Test that cached geocode_query calls underlying function."""
        from nohiki_geo_utils import create_cached_geocoder

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock()

        def cache_factory() -> MagicMock:
            return mock_cache

        cached_query, _ = create_cached_geocoder(cache_factory)

        mock_result = MagicMock()
        mock_result.latitude = 40.7128
        mock_result.longitude = -74.0060

        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(return_value=mock_result)
        mock_geocoder.__aenter__ = AsyncMock(return_value=mock_geocoder)
        mock_geocoder.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("nohiki_geo_utils.geocoder._create_geocoder", return_value=mock_geocoder),
            patch("nohiki_redis_utils.rate_limit_decorator.create_rate_limiter") as mock_limiter,
        ):
            mock_limiter_instance = MagicMock()
            mock_limiter_instance.check = AsyncMock(return_value=MagicMock(allowed=True, retry_after=None))
            mock_limiter.return_value = mock_limiter_instance

            result = await cached_query("New York, NY")

            assert result is not None
            assert result.latitude == pytest.approx(40.7128)

    async def test_cached_geocode_location_already_geocoded(self) -> None:
        """Test cached_geocode_location with already geocoded location."""
        from nohiki_geo_utils import create_cached_geocoder

        mock_cache = MagicMock()

        def cache_factory() -> MagicMock:
            return mock_cache

        _, cached_location = create_cached_geocoder(cache_factory)

        location = Location(
            city="New York",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=40.7128, longitude=-74.0060),
        )

        result = await cached_location(location)
        assert result.coordinates is not None
        assert result.coordinates.latitude == pytest.approx(40.7128)

    async def test_cached_geocode_location_empty_query(self) -> None:
        """Test cached_geocode_location with empty query result."""
        from nohiki_geo_utils import create_cached_geocoder

        mock_cache = MagicMock()

        def cache_factory() -> MagicMock:
            return mock_cache

        _, cached_location = create_cached_geocoder(cache_factory)

        location = Location()

        result = await cached_location(location)
        assert result.coordinates is None

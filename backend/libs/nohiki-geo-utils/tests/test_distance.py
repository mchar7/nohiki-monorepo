"""Tests for distance calculation utilities."""

from __future__ import annotations

import pytest
from nohiki.common.v1 import (
    CountryCode,
    GeoCoordinates,
    Location,
    LocationType,
)
from nohiki_geo_utils.distance import (
    GeodesicEstimator,
    calculate_distance,
)


class TestCalculateDistance:
    """Tests for calculate_distance function."""

    def test_returns_none_when_loc1_is_none(self) -> None:
        loc2 = Location(
            city="San Francisco",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        assert calculate_distance(None, loc2) is None

    def test_returns_none_when_loc2_is_none(self) -> None:
        loc1 = Location(
            city="San Francisco",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        assert calculate_distance(loc1, None) is None

    def test_returns_none_when_coords_missing(self) -> None:
        loc1 = Location(city="San Francisco", country=CountryCode.USA, location_type=LocationType.PHYSICAL)
        loc2 = Location(city="Los Angeles", country=CountryCode.USA, location_type=LocationType.PHYSICAL)
        assert calculate_distance(loc1, loc2) is None

    def test_calculates_distance_between_cities(self) -> None:
        sf = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        la = Location(
            city="Los Angeles",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=34.0522, longitude=-118.2437),
        )
        result = calculate_distance(sf, la)

        assert result is not None
        assert 550 < result.distance_km < 620
        assert result.is_same_state is True
        assert result.is_same_country is True
        assert result.is_same_city is False

    def test_same_location_returns_zero_distance(self) -> None:
        loc = Location(
            city="San Francisco",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        result = calculate_distance(loc, loc)

        assert result is not None
        assert result.distance_km == pytest.approx(0.0)
        assert result.is_same_city is True

    def test_detects_same_city(self) -> None:
        loc1 = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        loc2 = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7849, longitude=-122.4094),
        )
        result = calculate_distance(loc1, loc2)

        assert result is not None
        assert result.is_same_city is True
        assert result.distance_km < 5

    def test_different_countries(self) -> None:
        sf = Location(
            city="San Francisco",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        london = Location(
            city="London",
            country=CountryCode.GBR,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=51.5074, longitude=-0.1278),
        )
        result = calculate_distance(sf, london)

        assert result is not None
        assert result.is_same_country is False
        assert result.distance_km > 8000


class TestGeodesicEstimator:
    """Tests for GeodesicEstimator class."""

    def test_estimate_returns_correct_distance(self) -> None:
        estimator = GeodesicEstimator()
        origin = Location(
            city="San Francisco",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
        )
        destination = Location(
            city="Los Angeles",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=34.0522, longitude=-118.2437),
        )

        result = estimator.estimate(origin, destination)

        assert 550 < result.distance_km < 620
        assert result.method == "geodesic"
        assert result.duration_minutes is None
        assert result.transit_mode_used is None

    def test_estimate_raises_without_coordinates(self) -> None:
        estimator = GeodesicEstimator()
        origin = Location(city="San Francisco", country=CountryCode.USA, location_type=LocationType.PHYSICAL)
        destination = Location(
            city="Los Angeles",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
            coordinates=GeoCoordinates(latitude=34.0522, longitude=-118.2437),
        )

        with pytest.raises(ValueError, match="Both locations must have coordinates"):
            estimator.estimate(origin, destination)

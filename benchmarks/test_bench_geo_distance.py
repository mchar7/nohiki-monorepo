"""Benchmarks for geodesic distance calculation (nohiki-geo-utils).

The LocationScorer calls calculate_distance() per preferred location per candidate.
With 2-3 preferred locations and 150 candidates, this runs 300-450 times per scoring run.
"""

from __future__ import annotations

import pytest
from geopy.distance import geodesic
from nohiki.common.v1 import CountryCode, GeoCoordinates, Location, LocationType
from nohiki_geo_utils import calculate_distance

# Realistic location fixtures

_SF = Location(
    city="San Francisco",
    state_province="CA",
    country=CountryCode.USA,
    coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
    location_type=LocationType.PHYSICAL,
)

_NYC = Location(
    city="New York",
    state_province="NY",
    country=CountryCode.USA,
    coordinates=GeoCoordinates(latitude=40.7128, longitude=-74.0060),
    location_type=LocationType.PHYSICAL,
)

_LONDON = Location(
    city="London",
    state_province="",
    country=CountryCode.GBR,
    coordinates=GeoCoordinates(latitude=51.5074, longitude=-0.1278),
    location_type=LocationType.PHYSICAL,
)

_OAKLAND = Location(
    city="Oakland",
    state_province="CA",
    country=CountryCode.USA,
    coordinates=GeoCoordinates(latitude=37.8044, longitude=-122.2712),
    location_type=LocationType.PHYSICAL,
)


# Raw geopy.distance.geodesic (the underlying computation)


def test_bench_geodesic_raw_short(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark raw geodesic distance: SF to Oakland (~13 km)."""
    benchmark(
        geodesic,
        (37.7749, -122.4194),
        (37.8044, -122.2712),
    )


def test_bench_geodesic_raw_medium(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark raw geodesic distance: SF to NYC (~4,139 km)."""
    benchmark(
        geodesic,
        (37.7749, -122.4194),
        (40.7128, -74.0060),
    )


def test_bench_geodesic_raw_long(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark raw geodesic distance: SF to London (~8,616 km)."""
    benchmark(
        geodesic,
        (37.7749, -122.4194),
        (51.5074, -0.1278),
    )


# Full calculate_distance (with proto field access + admin matching)


def test_bench_calculate_distance_short(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full calculate_distance: SF to Oakland (same state)."""
    benchmark(calculate_distance, _SF, _OAKLAND)


def test_bench_calculate_distance_medium(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full calculate_distance: SF to NYC (same country)."""
    benchmark(calculate_distance, _SF, _NYC)


def test_bench_calculate_distance_cross_country(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark full calculate_distance: SF to London (cross-country)."""
    benchmark(calculate_distance, _SF, _LONDON)


def test_bench_calculate_distance_no_coords(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark calculate_distance with missing coordinates (early return)."""
    no_coords = Location(city="Unknown", state_province="", country=CountryCode.USA)
    benchmark(calculate_distance, _SF, no_coords)


# Batch simulation (typical scoring pipeline pattern)


def test_bench_distance_batch_3_locations_150_candidates(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark distance calculation: 3 preferred locations x 150 candidates."""
    preferred = [_SF, _NYC, _LONDON]
    candidates = [_OAKLAND, _SF, _NYC] * 50  # 150 candidates

    def batch() -> list[float]:
        results = []
        for candidate in candidates:
            min_dist = float("inf")
            for pref in preferred:
                result = calculate_distance(candidate, pref)
                if result is not None and result.distance_km < min_dist:
                    min_dist = result.distance_km
            results.append(min_dist)
        return results

    benchmark(batch)


# Admin-unit matching (no coordinates, string comparison fallback)


def test_bench_admin_city_match(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark admin-unit city matching (string normalization)."""

    def match() -> bool:
        city1 = "San Francisco"
        city2 = "san francisco"
        state1 = "CA"
        state2 = "ca"
        return city1.lower().strip() == city2.lower().strip() and state1.lower().strip() == state2.lower().strip()

    benchmark(match)

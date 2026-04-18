"""Tests for normalization functions."""

from job_query_composition_service.services.normalization import (
    canonicalize_locations,
    extract_remote_pref,
    normalize_keywords,
)
from nohiki.common.v1 import CountryCode, Location, LocationType


class TestNormalizeKeywords:
    """Tests for normalize_keywords function."""

    def test_lowercase_and_strip(self) -> None:
        keywords = ["  Python  ", "JAVA", " React "]
        result = normalize_keywords(keywords)
        assert result == ["java", "python", "react"]

    def test_removes_duplicates(self) -> None:
        keywords = ["python", "Python", "PYTHON"]
        result = normalize_keywords(keywords)
        assert result == ["python"]

    def test_removes_empty_strings(self) -> None:
        keywords = ["python", "", "  ", "java"]
        result = normalize_keywords(keywords)
        assert result == ["java", "python"]

    def test_sorts_alphabetically(self) -> None:
        keywords = ["zebra", "apple", "mango"]
        result = normalize_keywords(keywords)
        assert result == ["apple", "mango", "zebra"]


class TestCanonicalizeLocations:
    """Tests for canonicalize_locations function."""

    def test_normalizes_city_and_region_lowercase(self) -> None:
        locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                state_province="California",
                city="San Francisco",
            ).to_dict()
        ]
        result = canonicalize_locations(locations)
        assert result[0]["state_province"] == "california"
        assert result[0]["city"] == "san francisco"

    def test_removes_duplicates(self) -> None:
        locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                state_province="CA",
                city="SF",
            ).to_dict(),
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                state_province="ca",
                city="sf",
            ).to_dict(),
        ]
        result = canonicalize_locations(locations)
        assert len(result) == 1

    def test_sorts_by_country_region_city(self) -> None:
        locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                state_province="NY",
                city="NYC",
            ).to_dict(),
            Location(
                country=CountryCode.CAN,
                location_type=LocationType.PHYSICAL,
                state_province="ON",
                city="Toronto",
            ).to_dict(),
        ]
        result = canonicalize_locations(locations)
        assert result[0]["country"] == "CAN"
        assert result[1]["country"] == "USA"


class TestExtractRemotePref:
    """Tests for extract_remote_pref function."""

    def test_remote_only(self) -> None:
        locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.REMOTE,
                city="",
            ).to_dict()
        ]
        assert extract_remote_pref(locations) == "remote"

    def test_onsite_only(self) -> None:
        locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                city="NYC",
            ).to_dict()
        ]
        assert extract_remote_pref(locations) == "onsite"

    def test_hybrid(self) -> None:
        locations = [
            Location(
                country=CountryCode.USA,
                location_type=LocationType.REMOTE,
                city="",
            ).to_dict(),
            Location(
                country=CountryCode.USA,
                location_type=LocationType.PHYSICAL,
                city="NYC",
            ).to_dict(),
        ]
        assert extract_remote_pref(locations) == "hybrid"

    def test_any_when_empty(self) -> None:
        locations: list[dict[str, object]] = []
        assert extract_remote_pref(locations) == "any"

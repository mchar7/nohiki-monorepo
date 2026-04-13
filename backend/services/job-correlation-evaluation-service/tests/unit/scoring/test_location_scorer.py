"""Tests for LocationScorer."""

from __future__ import annotations

import math

import pytest
from job_correlation_evaluation_service.services.scoring.features.location_scorer import (
    LocationScenario,
    LocationScorer,
    LocationScoringConfig,
)
from nohiki.common.v1 import CountryCode, GeoCoordinates, Location, LocationType, WorkArrangement


@pytest.fixture
def scorer() -> LocationScorer:
    """Create a LocationScorer with default config."""
    return LocationScorer()


@pytest.fixture
def remote_location() -> Location:
    """Create a remote location."""
    return Location(location_type=LocationType.REMOTE)


@pytest.fixture
def nyc_location() -> Location:
    """Create a NYC location with coordinates."""
    return Location(
        city="New York",
        state_province="NY",
        country=CountryCode.USA,
        location_type=LocationType.PHYSICAL,
        coordinates=GeoCoordinates(latitude=40.7128, longitude=-74.0060),
    )


@pytest.fixture
def sf_location() -> Location:
    """Create a SF location with coordinates."""
    return Location(
        city="San Francisco",
        state_province="CA",
        country=CountryCode.USA,
        location_type=LocationType.PHYSICAL,
        coordinates=GeoCoordinates(latitude=37.7749, longitude=-122.4194),
    )


@pytest.fixture
def oakland_location() -> Location:
    """Create an Oakland location with coordinates (near SF)."""
    return Location(
        city="Oakland",
        state_province="CA",
        country=CountryCode.USA,
        location_type=LocationType.PHYSICAL,
        coordinates=GeoCoordinates(latitude=37.8044, longitude=-122.2712),
    )


class TestLocationScorerNaNHandling:
    """Tests for NaN handling in LocationScorer."""

    def test_no_user_preferences_returns_nan(self, scorer: LocationScorer, nyc_location: Location) -> None:
        """No user preferences → NaN (can't score without knowing what they want)."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[],
        )

        assert math.isnan(result.score)
        assert not result.is_scoreable
        assert result.fallback_reason == "no_preferences"

    def test_unknown_job_location_returns_nan(self, scorer: LocationScorer, nyc_location: Location) -> None:
        """Unknown job location → NaN."""
        result = scorer.score(
            job_location=None,
            profile_locations=[nyc_location],
        )

        assert math.isnan(result.score)
        assert not result.is_scoreable
        assert result.fallback_reason == "unknown_job_location"

    def test_remote_job_physical_preference_returns_nan(
        self, scorer: LocationScorer, remote_location: Location, nyc_location: Location
    ) -> None:
        """Remote job but user only wants physical locations → uncertain → NaN."""
        result = scorer.score(
            job_location=remote_location,
            profile_locations=[nyc_location],
        )

        assert math.isnan(result.score)
        assert not result.is_scoreable
        assert result.fallback_reason == "remote_job_physical_preference"

    def test_no_admin_match_returns_nan(self, scorer: LocationScorer) -> None:
        """Job in different country with no coordinate match → NaN."""
        job = Location(
            city="London",
            country=CountryCode.GBR,
            location_type=LocationType.PHYSICAL,
        )
        pref = Location(
            city="Tokyo",
            country=CountryCode.AUS,  # Different country
            location_type=LocationType.PHYSICAL,
        )
        result = scorer.score(job_location=job, profile_locations=[pref])

        assert math.isnan(result.score)
        assert not result.is_scoreable
        assert result.fallback_reason == "no_admin_match"


class TestLocationScorerRemoteJobs:
    """Tests for remote job scoring."""

    def test_remote_job_remote_preference_returns_1(self, scorer: LocationScorer, remote_location: Location) -> None:
        """Remote job + remote preference → perfect match."""
        result = scorer.score(
            job_location=remote_location,
            profile_locations=[remote_location],
        )

        assert result.score == pytest.approx(1.0)
        assert result.is_scoreable
        assert result.fallback_reason is None

    def test_remote_work_arrangement_matches_remote_preference(
        self, scorer: LocationScorer, remote_location: Location, nyc_location: Location
    ) -> None:
        """Job with REMOTE work arrangement + remote preference → perfect match."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[remote_location],
            job_work_arrangement=WorkArrangement.REMOTE,
        )

        assert result.score == pytest.approx(1.0)
        assert result.is_scoreable


class TestLocationScorerDistanceBased:
    """Tests for distance-based scoring."""

    def test_same_city_high_score(self, scorer: LocationScorer, nyc_location: Location) -> None:
        """Same city with coordinates → high score."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[nyc_location],
        )

        assert result.score >= 0.9
        assert result.is_scoreable

    def test_nearby_cities_good_score(
        self, scorer: LocationScorer, sf_location: Location, oakland_location: Location
    ) -> None:
        """Nearby cities (~15km) → good score."""
        result = scorer.score(
            job_location=sf_location,
            profile_locations=[oakland_location],
        )

        assert result.is_scoreable
        assert result.distance_km is not None
        assert 10 < result.distance_km < 20
        assert result.score > 0.7

    def test_distant_cities_lower_score(
        self, scorer: LocationScorer, nyc_location: Location, sf_location: Location
    ) -> None:
        """Distant cities (NYC to SF ~4000km) → low score."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[sf_location],
        )

        assert result.is_scoreable
        assert result.distance_km is not None
        assert result.distance_km > 3000
        assert result.score < 0.2

    def test_hybrid_job_distance_boost(
        self, scorer: LocationScorer, sf_location: Location, oakland_location: Location
    ) -> None:
        """Hybrid work arrangement gets distance boost."""
        onsite_result = scorer.score(
            job_location=sf_location,
            profile_locations=[oakland_location],
            job_work_arrangement=WorkArrangement.ON_SITE,
        )
        hybrid_result = scorer.score(
            job_location=sf_location,
            profile_locations=[oakland_location],
            job_work_arrangement=WorkArrangement.HYBRID,
        )

        assert hybrid_result.score >= onsite_result.score


class TestLocationScorerAdminUnits:
    """Tests for administrative unit fallback scoring."""

    def test_city_match_without_coordinates(self, scorer: LocationScorer) -> None:
        """Same city without coordinates → high score via admin match."""
        job = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        pref = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        result = scorer.score(job_location=job, profile_locations=[pref])

        assert result.score == pytest.approx(0.95)
        assert result.is_scoreable
        assert result.fallback_reason == "admin_city_match"

    def test_state_match_moderate_score(self, scorer: LocationScorer) -> None:
        """Same state, different city → moderate score."""
        job = Location(
            city="Oakland",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        pref = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        result = scorer.score(job_location=job, profile_locations=[pref])

        assert result.score == pytest.approx(0.75)
        assert result.is_scoreable

    def test_country_match_lower_score(self, scorer: LocationScorer) -> None:
        """Same country, different state → lower score."""
        job = Location(
            city="Austin",
            state_province="TX",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        pref = Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        )
        result = scorer.score(job_location=job, profile_locations=[pref])

        assert result.score == pytest.approx(0.55)
        assert result.is_scoreable


class TestLocationScorerScenarioDetection:
    """Tests for scenario detection logic."""

    def test_detects_relocation_scenario(self, scorer: LocationScorer, nyc_location: Location) -> None:
        """open_to_relocation=True → RELOCATION scenario."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[nyc_location],
            open_to_relocation=True,
        )

        assert result.scenario == LocationScenario.RELOCATION

    def test_detects_remote_only_scenario(self, scorer: LocationScorer, remote_location: Location) -> None:
        """Only remote preferences → REMOTE_ONLY scenario."""
        result = scorer.score(
            job_location=remote_location,
            profile_locations=[remote_location],
        )

        assert result.scenario == LocationScenario.REMOTE_ONLY

    def test_detects_flexible_scenario(self, scorer: LocationScorer, nyc_location: Location) -> None:
        """Multiple work arrangements including remote → FLEXIBLE scenario."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[nyc_location],
            user_work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
        )

        assert result.scenario == LocationScenario.FLEXIBLE

    def test_detects_local_commute_scenario(self, scorer: LocationScorer, nyc_location: Location) -> None:
        """Physical preferences only → LOCAL_COMMUTE scenario."""
        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[nyc_location],
        )

        assert result.scenario == LocationScenario.LOCAL_COMMUTE


class TestLocationScorerMultipleLocations:
    """Tests for handling multiple user locations."""

    def test_finds_best_match(
        self,
        scorer: LocationScorer,
        sf_location: Location,
        nyc_location: Location,
        oakland_location: Location,
    ) -> None:
        """Finds closest user location for scoring."""
        result = scorer.score(
            job_location=sf_location,
            profile_locations=[nyc_location, oakland_location],
        )

        assert result.is_scoreable
        assert result.distance_km is not None
        assert result.distance_km < 20

    def test_skips_remote_locations_in_physical_matching(
        self, scorer: LocationScorer, sf_location: Location, oakland_location: Location
    ) -> None:
        """Skips remote locations when matching physical job."""
        remote_loc = Location(location_type=LocationType.REMOTE)
        result = scorer.score(
            job_location=sf_location,
            profile_locations=[remote_loc, oakland_location],
        )

        assert result.is_scoreable
        assert result.distance_km is not None
        assert 10 < result.distance_km < 20


class TestLocationScorerConfig:
    """Tests for LocationScoringConfig."""

    def test_custom_config(self, nyc_location: Location) -> None:
        """Custom config is used."""
        config = LocationScoringConfig(
            decay_beta=0.1,
            hybrid_distance_multiplier=2.0,
        )
        scorer = LocationScorer(config)

        result = scorer.score(
            job_location=nyc_location,
            profile_locations=[nyc_location],
        )

        assert result.is_scoreable

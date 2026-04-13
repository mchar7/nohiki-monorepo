"""Location scoring for L2R feature extraction.

This module implements location-based scoring for job-candidate matching.
All scoring logic is local to this service; nohiki-geo-utils provides only
pure geodesic distance calculation.

Scoring Strategy:
1. Remote job + remote preference → 1.0
2. Remote job + no remote preference → NaN (let model decide from training data)
3. On-site/hybrid → distance-based decay
4. Missing data → NaN with validity flag
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from nohiki.common.v1 import Location, LocationType, WorkArrangement
from nohiki_geo_utils import calculate_distance

from job_correlation_evaluation_service.services.scoring.config import (
    LocationScoringConfig,
    get_scoring_service_settings,
)


class LocationScenario(Enum):
    """Detected user search scenario based on preferences."""

    LOCAL_COMMUTE = "local_commute"
    RELOCATION = "relocation"
    REMOTE_ONLY = "remote_only"
    FLEXIBLE = "flexible"


@dataclass(frozen=True, slots=True)
class LocationMatchResult:
    """Result of location matching."""

    score: float  # [0, 1] or math.nan if not scoreable
    is_scoreable: bool  # False if score is NaN
    scenario: LocationScenario
    distance_km: float | None
    is_same_city: bool  # True if job and user are in same city
    fallback_reason: str | None  # Why NaN was returned


class LocationScorer:
    """Location scorer for L2R features.

    Returns NaN (not arbitrary fallback values) when data is insufficient.
    The validity flag in the feature vector signals this to the model.
    """

    _MIN_SCORE_THRESHOLD: float = 0.01

    def __init__(self, config: LocationScoringConfig | None = None) -> None:
        """Initialize scorer with optional config.

        Args:
            config: Optional location scoring configuration.
                If not provided, uses default from get_scoring_service_settings().

        """
        self._config = config if config is not None else get_scoring_service_settings().location

    def score(
        self,
        job_location: Location | None,
        profile_locations: Sequence[Location],
        *,
        job_work_arrangement: WorkArrangement = WorkArrangement.UNSPECIFIED,
        user_work_arrangements: Sequence[WorkArrangement] | None = None,
        open_to_relocation: bool = False,
    ) -> LocationMatchResult:
        """Score job location against user preferences.

        Returns NaN when:
        - Job location is unknown
        - User has no location preferences
        - Remote job but user has no remote preference (uncertain compatibility)
        """
        scenario = self._detect_scenario(
            profile_locations, user_work_arrangements, open_to_relocation=open_to_relocation
        )

        if not profile_locations:
            return LocationMatchResult(
                score=math.nan,
                is_scoreable=False,
                scenario=scenario,
                distance_km=None,
                is_same_city=False,
                fallback_reason="no_preferences",
            )

        if job_location is None:
            return LocationMatchResult(
                score=math.nan,
                is_scoreable=False,
                scenario=scenario,
                distance_km=None,
                is_same_city=False,
                fallback_reason="unknown_job_location",
            )

        if self._is_remote_job(job_location, job_work_arrangement):
            return self._score_remote_job(profile_locations, scenario)

        result = self._score_by_coordinates(job_location, profile_locations, scenario, job_work_arrangement)
        if result is not None:
            return result

        return self._score_by_admin_units(job_location, profile_locations, scenario)

    def _detect_scenario(
        self,
        profile_locations: Sequence[Location],
        user_work_arrangements: Sequence[WorkArrangement] | None,
        *,
        open_to_relocation: bool,
    ) -> LocationScenario:
        """Detect user's search scenario from preferences."""
        if open_to_relocation:
            return LocationScenario.RELOCATION

        if user_work_arrangements:
            arrangements_set = set(user_work_arrangements)
            if arrangements_set == {WorkArrangement.REMOTE}:
                return LocationScenario.REMOTE_ONLY
            if WorkArrangement.REMOTE in arrangements_set and len(arrangements_set) > 1:
                return LocationScenario.FLEXIBLE

        if any(loc.location_type == LocationType.REMOTE for loc in profile_locations):
            return LocationScenario.REMOTE_ONLY

        return LocationScenario.LOCAL_COMMUTE

    def _is_remote_job(self, location: Location, work_arrangement: WorkArrangement) -> bool:
        """Check if job is fully remote."""
        return work_arrangement == WorkArrangement.REMOTE or location.location_type == LocationType.REMOTE

    def _score_remote_job(
        self, profile_locations: Sequence[Location], scenario: LocationScenario
    ) -> LocationMatchResult:
        """Score a remote job against user preferences."""
        has_remote_pref = any(loc.location_type == LocationType.REMOTE for loc in profile_locations)

        if has_remote_pref:
            return LocationMatchResult(
                score=1.0,
                is_scoreable=True,
                scenario=scenario,
                distance_km=None,
                is_same_city=False,
                fallback_reason=None,
            )

        return LocationMatchResult(
            score=math.nan,
            is_scoreable=False,
            scenario=scenario,
            distance_km=None,
            is_same_city=False,
            fallback_reason="remote_job_physical_preference",
        )

    def _score_by_coordinates(
        self,
        job_location: Location,
        profile_locations: Sequence[Location],
        scenario: LocationScenario,
        work_arrangement: WorkArrangement,
    ) -> LocationMatchResult | None:
        """Score using coordinate-based distance. Returns None if no coordinates."""
        if job_location.coordinates is None:
            return None

        min_distance, found_same_city = self._find_minimum_distance(job_location, profile_locations)
        if min_distance is None:
            return None

        effective_distance = self._apply_hybrid_adjustment(min_distance, work_arrangement)
        score = self._compute_distance_score(effective_distance, scenario)

        return self._build_coordinate_result(score, scenario, min_distance, found_same_city=found_same_city)

    def _find_minimum_distance(
        self,
        job_location: Location,
        profile_locations: Sequence[Location],
    ) -> tuple[float | None, bool]:
        """Find minimum distance to any preferred location."""
        min_distance: float | None = None
        found_same_city = False

        for pref_loc in profile_locations:
            if pref_loc.location_type == LocationType.REMOTE:
                continue

            distance_result = calculate_distance(job_location, pref_loc)
            if distance_result is None:
                continue

            if distance_result.is_same_city:
                found_same_city = True

            if min_distance is None or distance_result.distance_km < min_distance:
                min_distance = distance_result.distance_km

        return min_distance, found_same_city

    def _apply_hybrid_adjustment(self, distance: float, work_arrangement: WorkArrangement) -> float:
        """Apply hybrid distance multiplier if applicable."""
        if work_arrangement == WorkArrangement.HYBRID:
            return distance / self._config.hybrid_distance_multiplier
        return distance

    def _compute_distance_score(self, effective_distance: float, scenario: LocationScenario) -> float:
        """Compute score based on distance and scenario."""
        if scenario == LocationScenario.RELOCATION:
            return self._exponential_decay(
                effective_distance,
                self._config.decay_beta * self._config.relocation_decay_multiplier,
            )
        return self._piecewise_linear_score(effective_distance)

    def _build_coordinate_result(
        self,
        score: float,
        scenario: LocationScenario,
        min_distance: float,
        *,
        found_same_city: bool,
    ) -> LocationMatchResult:
        """Build LocationMatchResult for coordinate-based scoring."""
        if found_same_city and min_distance < self._config.same_city_threshold_km:
            return LocationMatchResult(
                score=self._config.city_match_score,
                is_scoreable=True,
                scenario=scenario,
                distance_km=min_distance,
                is_same_city=True,
                fallback_reason="same_city_coordinate_match",
            )

        return LocationMatchResult(
            score=score,
            is_scoreable=True,
            scenario=scenario,
            distance_km=min_distance,
            is_same_city=found_same_city,
            fallback_reason=None,
        )

    @staticmethod
    def _normalize_admin_field(value: str | None) -> str:
        """Normalize administrative field for comparison."""
        return (value or "").lower().strip()

    def _check_city_match(
        self,
        job_city: str,
        job_state: str,
        pref_city: str,
        pref_state: str,
    ) -> bool:
        """Check if job and preference match at city level."""
        if not (job_city and pref_city and job_city == pref_city):
            return False
        return job_state == pref_state or not pref_state

    def _compute_region_score(
        self,
        job_state: str,
        job_country: object,
        pref_state: str,
        pref_country: object,
    ) -> float:
        """Compute score for state or country level match."""
        if job_state and pref_state and job_state == pref_state:
            return self._config.state_match_score
        if job_country and pref_country and job_country == pref_country:
            return self._config.country_match_score
        return 0.0

    def _score_by_admin_units(
        self,
        job_location: Location,
        profile_locations: Sequence[Location],
        scenario: LocationScenario,
    ) -> LocationMatchResult:
        """Fallback scoring using administrative unit matching."""
        job_city = self._normalize_admin_field(job_location.city)
        job_state = self._normalize_admin_field(job_location.state_province)
        job_country = job_location.country

        best_score = 0.0

        for pref in profile_locations:
            if pref.location_type == LocationType.REMOTE:
                continue

            pref_city = self._normalize_admin_field(pref.city)
            pref_state = self._normalize_admin_field(pref.state_province)

            if self._check_city_match(job_city, job_state, pref_city, pref_state):
                return self._build_city_match_result(scenario)

            region_score = self._compute_region_score(job_state, job_country, pref_state, pref.country)
            best_score = max(best_score, region_score)

        return self._build_admin_result(best_score, scenario)

    def _build_city_match_result(self, scenario: LocationScenario) -> LocationMatchResult:
        """Build result for city-level match."""
        return LocationMatchResult(
            score=self._config.city_match_score,
            is_scoreable=True,
            scenario=scenario,
            distance_km=None,
            is_same_city=True,
            fallback_reason="admin_city_match",
        )

    def _build_admin_result(self, best_score: float, scenario: LocationScenario) -> LocationMatchResult:
        """Build result for administrative unit matching."""
        if best_score < self._MIN_SCORE_THRESHOLD:
            return LocationMatchResult(
                score=math.nan,
                is_scoreable=False,
                scenario=scenario,
                distance_km=None,
                is_same_city=False,
                fallback_reason="no_admin_match",
            )

        return LocationMatchResult(
            score=best_score,
            is_scoreable=True,
            scenario=scenario,
            distance_km=None,
            is_same_city=False,
            fallback_reason="admin_partial_match",
        )

    def _exponential_decay(self, distance_km: float, beta: float) -> float:
        """Exponential decay: e^(-beta * distance)."""
        if distance_km <= 0:
            return 1.0
        return math.exp(-beta * distance_km)

    def _piecewise_linear_score(self, distance_km: float) -> float:
        """Piecewise linear scoring based on commute breakpoints."""
        if distance_km <= 0:
            return 1.0

        breakpoints = self._config.commute_breakpoints
        for i in range(len(breakpoints) - 1):
            d1, s1 = breakpoints[i]
            d2, s2 = breakpoints[i + 1]
            if d1 <= distance_km < d2:
                t = (distance_km - d1) / (d2 - d1)
                return s1 + t * (s2 - s1)

        return 0.0

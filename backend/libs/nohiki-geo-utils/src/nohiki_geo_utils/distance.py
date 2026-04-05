"""Distance calculation utilities.

Geodesic distance calculation between Location proto objects.
For L2R scoring, see job-correlation-evaluation-service/services/scoring/features/location_scorer.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from geopy.distance import geodesic

if TYPE_CHECKING:
    from nohiki.common.v1 import Location


PRECISION_CONFIDENCE: dict[int, float] = {
    0: 0.5,  # UNSPECIFIED
    1: 1.0,  # EXACT_ADDRESS
    2: 0.9,  # NEIGHBORHOOD
    3: 0.6,  # CITY_CENTER
    4: 0.3,  # REGION_CENTER
    5: 0.1,  # COUNTRY_CENTER
}


@dataclass(frozen=True, slots=True)
class EstimationResult:
    """Result from a DistanceEstimator."""

    distance_km: float
    duration_minutes: float | None
    confidence: float
    method: str
    transit_mode_used: int | None


@dataclass(frozen=True, slots=True)
class DistanceResult:
    """Result of distance calculation between two locations."""

    distance_km: float
    distance_miles: float
    is_same_city: bool
    is_same_state: bool
    is_same_country: bool
    confidence: float
    job_precision: int
    user_precision: int


@runtime_checkable
class DistanceEstimator(Protocol):
    """Protocol for distance/commute estimation."""

    def estimate(
        self,
        origin: Location,
        destination: Location,
    ) -> EstimationResult:
        """Estimate distance/time between two locations."""
        ...


def _get_location_precision(location: Location) -> int:
    """Extract precision from Location proto, defaulting to 0 (UNSPECIFIED)."""
    return getattr(location, "precision", 0) or 0


class GeodesicEstimator:
    """MVP distance estimator using geopy.distance.geodesic."""

    def estimate(
        self,
        origin: Location,
        destination: Location,
    ) -> EstimationResult:
        """Estimate geodesic distance."""
        if origin.coordinates is None or destination.coordinates is None:
            msg = "Both locations must have coordinates"
            raise ValueError(msg)

        dist_km, _dist_miles = _cached_geodesic_distance(
            origin.coordinates.latitude,
            origin.coordinates.longitude,
            destination.coordinates.latitude,
            destination.coordinates.longitude,
        )

        origin_precision = _get_location_precision(origin)
        dest_precision = _get_location_precision(destination)
        confidence = min(
            PRECISION_CONFIDENCE.get(origin_precision, 0.5),
            PRECISION_CONFIDENCE.get(dest_precision, 0.5),
        )

        return EstimationResult(
            distance_km=dist_km,
            duration_minutes=None,
            confidence=confidence,
            method="geodesic",
            transit_mode_used=None,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# DISTANCE CALCULATION
# ═══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=4096)
def _cached_geodesic_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> tuple[float, float]:
    """Cached geodesic distance calculation.

    Args:
        lat1: Latitude of first point
        lon1: Longitude of first point
        lat2: Latitude of second point
        lon2: Longitude of second point

    Returns:
        Tuple of (distance_km, distance_miles)

    """
    dist = geodesic((lat1, lon1), (lat2, lon2))
    return (dist.kilometers, dist.miles)


def calculate_distance(
    loc1: Location | None,
    loc2: Location | None,
) -> DistanceResult | None:
    """Calculate geodesic distance between two Location proto objects.

    Uses geopy.distance.geodesic for accurate earth-surface distance.
    Includes precision-aware confidence scoring.

    Args:
        loc1: First location (must have coordinates)
        loc2: Second location (must have coordinates)

    Returns:
        DistanceResult with distance, context, and precision info
        None if coordinates unavailable

    """
    if loc1 is None or loc2 is None:
        return None

    coords1 = loc1.coordinates
    coords2 = loc2.coordinates

    if coords1 is None or coords2 is None:
        return None

    dist_km, dist_miles = _cached_geodesic_distance(
        coords1.latitude,
        coords1.longitude,
        coords2.latitude,
        coords2.longitude,
    )

    city1 = (loc1.city or "").lower().strip()
    city2 = (loc2.city or "").lower().strip()
    state1 = (loc1.state_province or "").lower().strip()
    state2 = (loc2.state_province or "").lower().strip()
    country1 = loc1.country
    country2 = loc2.country

    loc1_precision = _get_location_precision(loc1)
    loc2_precision = _get_location_precision(loc2)

    confidence = min(
        PRECISION_CONFIDENCE.get(loc1_precision, 0.5),
        PRECISION_CONFIDENCE.get(loc2_precision, 0.5),
    )

    return DistanceResult(
        distance_km=dist_km,
        distance_miles=dist_miles,
        is_same_city=bool(city1 and city2 and city1 == city2),
        is_same_state=bool(state1 and state2 and state1 == state2),
        is_same_country=country1 == country2 and country1 != 0,
        confidence=confidence,
        job_precision=loc1_precision,
        user_precision=loc2_precision,
    )

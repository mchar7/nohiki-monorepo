"""Geodesic distance calculation utilities."""

import importlib
from typing import TYPE_CHECKING

from nohiki_geo_utils.distance import (
    PRECISION_CONFIDENCE,
    DistanceEstimator,
    DistanceResult,
    EstimationResult,
    GeodesicEstimator,
    calculate_distance,
)

if TYPE_CHECKING:
    from nohiki_geo_utils.geocoder import COUNTRY_CODE_NAMES as COUNTRY_CODE_NAMES
    from nohiki_geo_utils.geocoder import build_geocode_query as build_geocode_query
    from nohiki_geo_utils.geocoder import create_cached_geocoder as create_cached_geocoder
    from nohiki_geo_utils.geocoder import geocode_location as geocode_location
    from nohiki_geo_utils.geocoder import geocode_query as geocode_query

__all__ = [
    "COUNTRY_CODE_NAMES",
    "PRECISION_CONFIDENCE",
    "DistanceEstimator",
    "DistanceResult",
    "EstimationResult",
    "GeodesicEstimator",
    "build_geocode_query",
    "calculate_distance",
    "create_cached_geocoder",
    "geocode_location",
    "geocode_query",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "COUNTRY_CODE_NAMES": ("nohiki_geo_utils.geocoder", "COUNTRY_CODE_NAMES"),
    "build_geocode_query": ("nohiki_geo_utils.geocoder", "build_geocode_query"),
    "create_cached_geocoder": ("nohiki_geo_utils.geocoder", "create_cached_geocoder"),
    "geocode_location": ("nohiki_geo_utils.geocoder", "geocode_location"),
    "geocode_query": ("nohiki_geo_utils.geocoder", "geocode_query"),
}


def __getattr__(name: str) -> object:
    """Lazy-import geocoding components (PEP 562)."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

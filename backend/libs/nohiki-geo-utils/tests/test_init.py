"""Tests for package initialization and lazy geocoder imports."""

from __future__ import annotations

import sys


def test_distance_export_does_not_load_geocoder_dependencies() -> None:
    """Keep GeoPy and Redis decorators unloaded until geocoding is requested."""
    lazy_prefixes = ("geopy", "nohiki_geo_utils", "nohiki_redis_utils")
    lazy_module_prefixes = tuple(f"{prefix}." for prefix in lazy_prefixes)
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name in lazy_prefixes or name.startswith(lazy_module_prefixes)
    }
    try:
        for name in saved:
            sys.modules.pop(name, None)

        from nohiki_geo_utils import calculate_distance

        assert callable(calculate_distance)
        assert "nohiki_geo_utils.geocoder" not in sys.modules
        assert not any(name == "geopy" or name.startswith("geopy.") for name in sys.modules)
        assert "nohiki_redis_utils.rate_limit_decorator" not in sys.modules

        from nohiki_geo_utils import build_geocode_query

        assert callable(build_geocode_query)
        assert "nohiki_geo_utils.geocoder" in sys.modules
        assert "nohiki_redis_utils.rate_limit_decorator" not in sys.modules
    finally:
        stale = [name for name in sys.modules if name in lazy_prefixes or name.startswith(lazy_module_prefixes)]
        for name in stale:
            del sys.modules[name]
        sys.modules.update(saved)

"""Normalization functions for query deduplication."""

from __future__ import annotations

import json
from typing import Any

from nohiki.common.v1 import Location, LocationType


def normalize_keywords(keywords: list[str]) -> list[str]:
    """Normalize and deduplicate keywords (lowercase, strip, sort)."""
    normalized = {kw.lower().strip() for kw in keywords if kw.strip()}
    return sorted(normalized)


def _normalize_location(loc: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single location dict with validated enums."""
    location = Location.from_dict(loc)
    return {
        "country": location.country.name,
        "location_type": location.location_type.name,
        "state_province": (location.state_province or "").lower().strip(),
        "city": (location.city or "").lower().strip(),
    }


def canonicalize_locations(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Canonicalize and deduplicate locations for consistent comparison."""
    seen: set[str] = set()
    canonical: list[dict[str, Any]] = []

    for loc in locations:
        normalized = _normalize_location(loc)
        key = json.dumps(normalized, sort_keys=True)
        if key not in seen:
            seen.add(key)
            canonical.append(normalized)

    return sorted(
        canonical,
        key=lambda x: (x["country"], x["location_type"], x["state_province"], x["city"]),
    )


def extract_remote_pref(locations: list[dict[str, Any]]) -> str:
    """Extract remote preference from locations.

    Args:
        locations: List of location dictionaries.

    Returns:
        One of: 'remote', 'onsite', 'hybrid', or 'any'.

    """
    parsed = [Location.from_dict(loc) for loc in locations]
    has_remote = any(loc.location_type == LocationType.REMOTE for loc in parsed)
    has_onsite = any(loc.location_type == LocationType.PHYSICAL and bool(loc.city) for loc in parsed)

    if has_remote and has_onsite:
        return "hybrid"
    if has_remote:
        return "remote"
    if has_onsite:
        return "onsite"
    return "any"

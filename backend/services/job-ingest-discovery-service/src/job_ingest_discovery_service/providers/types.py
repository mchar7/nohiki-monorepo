"""Provider type utilities.

Core types (DiscoveryRequest, DiscoveryResult, RawListing) are in core/models.py.
Helper functions for provider implementations.
"""

from __future__ import annotations

from nohiki.common.v1 import CountryCode

from job_ingest_discovery_service.core.models import DiscoveryLocation

COUNTRY_DISPLAY_NAMES: dict[CountryCode, str] = {
    CountryCode.USA: "United States",
    CountryCode.CAN: "Canada",
    CountryCode.GBR: "United Kingdom",
    CountryCode.DEU: "Germany",
    CountryCode.FRA: "France",
    CountryCode.NLD: "Netherlands",
    CountryCode.IRL: "Ireland",
    CountryCode.CHE: "Switzerland",
    CountryCode.AUS: "Australia",
    CountryCode.NZL: "New Zealand",
    CountryCode.SGP: "Singapore",
    CountryCode.IND: "India",
    CountryCode.ARE: "United Arab Emirates",
    CountryCode.ISR: "Israel",
}


def location_to_search_string(loc: DiscoveryLocation) -> str:
    """Build location string for provider search queries."""
    country_name = COUNTRY_DISPLAY_NAMES.get(loc.country)
    parts = [p for p in (loc.city, loc.region, country_name) if p]
    return ", ".join(parts) if parts else ""

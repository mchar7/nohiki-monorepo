"""Internal domain models for job discovery.

These are service-internal models that providers output.
Conversion to proto DiscoveredListing happens centrally in listing_factory.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from nohiki.common.v1 import (
    Compensation,
    CountryCode,
    JobBoardSource,
    WorkArrangement,
)


@dataclass(frozen=True, slots=True)
class DiscoveryLocation:
    """Location for discovery request."""

    city: str | None = None
    region: str | None = None
    country: CountryCode = CountryCode.UNSPECIFIED
    is_remote: bool = False


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    """Provider-agnostic discovery request.

    Immutable request object passed to providers.
    """

    query_id: str
    keywords: tuple[str, ...]
    sources: tuple[JobBoardSource, ...]
    locations: tuple[DiscoveryLocation, ...]
    work_arrangements: tuple[WorkArrangement, ...]
    results_per_source: int = 50
    hours_old: int | None = None


@dataclass(slots=True)
class RawListing:
    """Raw job listing from a provider.

    Provider-agnostic internal model. No proto dependencies in fields.
    Content hash is computed centrally, not by providers.
    """

    listing_url: str
    source: JobBoardSource
    title: str
    company: str
    description: str
    location_raw: str = ""
    external_id: str | None = None
    posted_at: datetime | None = None
    apply_url: str | None = None
    company_url: str | None = None
    compensation: Compensation | None = None
    logo_url: str | None = None
    raw_skills: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DiscoveryResult:
    """Result from a provider's discovery operation."""

    listings: list[RawListing]
    provider_name: str
    duration_seconds: float = 0.0
    error: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None

    @property
    def success(self) -> bool:
        """Return True if discovery completed without error."""
        return self.error is None

    @property
    def count(self) -> int:
        """Return number of listings found."""
        return len(self.listings)

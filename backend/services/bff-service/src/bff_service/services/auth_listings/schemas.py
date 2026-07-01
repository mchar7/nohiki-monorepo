"""Pydantic response models and pipeline data types for auth-listings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


class AuthListingItem(BaseModel):
    """A single job listing item in the auth-listings API response.

    Contains only the fields needed for decorative card display.
    Intentionally excludes id, listing_url, description, and weight
    to prevent information leakage on an unauthenticated endpoint.

    ``location_raw`` mirrors the underlying NOT NULL projection column;
    listings without a parsable location surface as the empty string,
    not ``None``.
    """

    title: str
    company_name: str
    location_raw: str
    work_arrangement: str | None
    required_skills: list[str]
    posted_at: datetime
    language: str | None


class AuthListingsResponse(BaseModel):
    """Response model for the auth-listings endpoint.

    Args:
        listings: Weighted, diversity-filtered job listings for card display.
        country: ISO 3166-1 alpha-3 country code used for geo-targeting.
    """

    listings: list[AuthListingItem]
    country: str


@dataclass(frozen=True, slots=True)
class WeightedCandidate:
    """Intermediate pipeline type carrying a listing with its computed weight.

    Frozen dataclass for pipeline efficiency: used between the weighting
    and diversity filter stages. Not a Pydantic model because it's never
    serialized to JSON; it's a transient in-memory structure.

    Attributes:
        title: Job listing title.
        company_name: Company name for diversity filtering.
        location_raw: Raw location string for card display.
        work_arrangement: Work arrangement type (remote, hybrid, etc.).
        required_skills: List of required skill names.
        posted_at: Publication timestamp.
        language: IETF BCP 47 language tag.
        weight: Computed relevance weight in [0, 1].
    """

    title: str
    company_name: str
    location_raw: str
    work_arrangement: str | None
    required_skills: list[str]
    posted_at: datetime
    language: str | None
    weight: float

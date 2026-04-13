"""Centralized conversion from internal RawListing to proto DiscoveredListing.

Single source of truth for internal → event model transformation.
Ensures consistent content hashing across all providers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from nohiki.job.ingest.v1 import DiscoveredListing

from job_ingest_discovery_service.core.content_hasher import compute_content_hash
from job_ingest_discovery_service.core.models import RawListing


def to_discovered_listing(raw: RawListing, discovered_at: datetime | None = None) -> DiscoveredListing:
    """Convert internal RawListing to proto DiscoveredListing.

    Centralizes:
    - Content hash computation (for cross-provider deduplication)
    - Timestamp normalization
    - Field mapping
    """
    now = discovered_at or datetime.now(UTC)
    content_hash = compute_content_hash(raw.title, raw.company, raw.description)

    posted_ts = _normalize_timestamp(raw.posted_at)
    if posted_ts is None:
        posted_ts = now  # Fallback to now if no posted timestamp available

    return DiscoveredListing(
        listing_url=raw.listing_url,
        source=raw.source,
        external_id=raw.external_id,
        title=raw.title,
        company_name=raw.company,
        description=raw.description,
        location_raw=raw.location_raw,
        compensation=raw.compensation,
        raw_skills=raw.raw_skills,
        apply_url=raw.apply_url,
        company_url=raw.company_url,
        company_logo_url=raw.logo_url,
        discovered_timestamp=now,
        posted_timestamp=posted_ts,
        content_hash=content_hash,
    )


def _normalize_timestamp(ts: datetime | None) -> datetime | None:
    """Ensure timestamp has UTC timezone."""
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)

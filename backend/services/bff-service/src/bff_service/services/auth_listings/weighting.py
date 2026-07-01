"""Weight computation for auth-listings candidate ranking."""

from __future__ import annotations

from datetime import UTC, datetime

from bff_service.services.auth_listings.constants import (
    GEOGRAPHIC_TIER_BACKFILL,
    GEOGRAPHIC_TIER_SAME_COUNTRY,
    LANGUAGE_MISMATCH_FACTOR,
    RECENCY_BRACKETS,
    RECENCY_FLOOR,
)


def compute_weight(
    posted_at: datetime,
    *,
    is_same_country: bool,
    listing_language: str | None,
    user_language: str | None,
    now: datetime | None = None,
) -> float:
    """Compute relevance weight for a job listing candidate.

    Formula: geographic_tier x recency_multiplier x language_bonus

    Geographic tier is 1.0 for same-country listings or 0.15 for backfill.
    Recency multiplier decays based on how old the listing is (bracket lookup).
    Language bonus is 1.0 when languages match or either is unknown, 0.7 when
    they differ.

    Args:
        posted_at: Publication timestamp of the listing.
        is_same_country: Whether the listing is in the user's country.
        listing_language: IETF BCP 47 language tag of the listing, or None.
        user_language: Preferred language of the user, or None.
        now: Pre-computed current timestamp. Falls back to datetime.now(UTC) if None.

    Returns:
        Relevance weight in the range [0, 1].
    """
    geo_tier = GEOGRAPHIC_TIER_SAME_COUNTRY if is_same_country else GEOGRAPHIC_TIER_BACKFILL

    age_days = ((now or datetime.now(UTC)) - posted_at).days
    recency = RECENCY_FLOOR
    for max_days, multiplier in RECENCY_BRACKETS:
        if age_days <= max_days:
            recency = multiplier
            break

    if not listing_language or not user_language or listing_language == user_language:
        lang_bonus = 1.0
    else:
        lang_bonus = LANGUAGE_MISMATCH_FACTOR

    return geo_tier * recency * lang_bonus

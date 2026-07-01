"""Auth-listings service orchestrator: composes query, weighting, and filtering stages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nohiki_observability import get_logger
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.core.config import AuthListingsSettings
from bff_service.services.auth_listings.filtering import apply_diversity_filter
from bff_service.services.auth_listings.queries import (
    fetch_backfill_candidates,
    fetch_global_candidates,
    fetch_primary_candidates,
)
from bff_service.services.auth_listings.schemas import (
    AuthListingItem,
    AuthListingsResponse,
    WeightedCandidate,
)
from bff_service.services.auth_listings.weighting import compute_weight

logger = get_logger(__name__)

# Known alpha-3 country codes from the CountryCode proto enum.
# Used to detect unrecognized countries that need global fallback.
_KNOWN_COUNTRIES: frozenset[str] = frozenset(
    {
        "USA",
        "CAN",
        "GBR",
        "DEU",
        "FRA",
        "NLD",
        "IRL",
        "CHE",
        "AUS",
        "NZL",
        "SGP",
        "IND",
        "ARE",
        "ISR",
    }
)


def _row_to_candidate(
    row: Row[Any],
    *,
    is_same_country: bool,
    user_language: str | None,
    now: datetime,
) -> WeightedCandidate:
    """Convert a DB row to a WeightedCandidate with computed weight.

    Args:
        row: SQLAlchemy result row containing auth-listing columns.
        is_same_country: Whether this listing shares the user's country.
        user_language: Preferred language of the user, or None.
        now: Pre-computed current timestamp for weight computation.

    Returns:
        WeightedCandidate with relevance weight computed from geo/recency/language.
    """
    weight = compute_weight(
        row.posted_at,
        is_same_country=is_same_country,
        listing_language=row.language,
        user_language=user_language,
        now=now,
    )
    return WeightedCandidate(
        title=row.title,
        company_name=row.company_name or "",
        location_raw=row.location_raw,
        work_arrangement=row.work_arrangement,
        required_skills=list(row.required_skills) if row.required_skills else [],
        posted_at=row.posted_at,
        language=row.language,
        weight=weight,
    )


async def compile_auth_listings(
    db: AsyncSession,
    country_code: str,
    *,
    user_language: str | None,
    settings: AuthListingsSettings,
) -> AuthListingsResponse:
    """Orchestrate the full auth-listings pipeline: query → weight → sort → filter → respond.

    Steps:
        1. Check country recognition: unrecognized countries fall back to global query.
        2. Fetch primary same-country candidates.
        3. Conditionally backfill with international candidates if primary pool is sparse.
        4. Compute relevance weights for all candidates.
        5. Sort by weight descending and apply company diversity filter.
        6. Map to response model.

    Args:
        db: Async database session.
        country_code: ISO 3166-1 alpha-3 country code for geo-targeting.
        user_language: Preferred language of the user, or None if unknown.
        settings: Auth-listings pipeline configuration.

    Returns:
        AuthListingsResponse containing diversity-filtered listing cards.
    """
    backfill_used = False
    now = datetime.now(UTC)

    # Step 1: Country recognition: unrecognized countries get global fallback
    if country_code not in _KNOWN_COUNTRIES:
        global_rows = await fetch_global_candidates(db, settings)
        all_candidates = [
            _row_to_candidate(row, is_same_country=False, user_language=user_language, now=now) for row in global_rows
        ]
        primary_count = 0
        backfill_count = len(all_candidates)
        backfill_used = True
    else:
        # Step 2: Primary same-country query
        primary_rows = await fetch_primary_candidates(db, country_code, settings)
        primary_weighted = [
            _row_to_candidate(row, is_same_country=True, user_language=user_language, now=now) for row in primary_rows
        ]
        primary_count = len(primary_weighted)

        # Step 3: Conditional backfill when primary pool is sparse
        backfill_weighted: list[WeightedCandidate] = []
        if primary_count < settings.backfill_threshold:
            backfill_rows = await fetch_backfill_candidates(db, country_code, settings)
            backfill_weighted = [
                _row_to_candidate(
                    row,
                    is_same_country=False,
                    user_language=user_language,
                    now=now,
                )
                for row in backfill_rows
            ]
            backfill_used = True

        backfill_count = len(backfill_weighted)

        # Step 5: Combine primary + backfill
        all_candidates = primary_weighted + backfill_weighted

    # Step 6: Sort by weight descending
    sorted_candidates = sorted(all_candidates, key=lambda c: c.weight, reverse=True)

    # Step 7: Apply diversity filter
    filtered = apply_diversity_filter(
        sorted_candidates,
        max_per_company=settings.max_per_company,
        max_total=settings.max_listings_returned,
    )

    # Step 8: Telemetry logging
    logger.info(
        "auth_listings_compiled",
        country=country_code,
        primary_count=primary_count,
        backfill_count=backfill_count,
        backfill_used=backfill_used,
        total_candidates=len(all_candidates),
        final_count=len(filtered),
    )

    # Step 9: Map to response
    listings = [
        AuthListingItem(
            title=c.title,
            company_name=c.company_name,
            location_raw=c.location_raw,
            work_arrangement=c.work_arrangement,
            required_skills=c.required_skills,
            posted_at=c.posted_at,
            language=c.language,
        )
        for c in filtered
    ]

    return AuthListingsResponse(listings=listings, country=country_code)

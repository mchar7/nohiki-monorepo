"""SQLAlchemy query builders for auth-listings candidate selection.

Each public function fetches job listing candidates from the
``JobListingProjection`` table with quality predicates (freshness,
non-null fields, minimum title length).  Two private helpers keep the
column list and WHERE predicates DRY across the three query variants.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm  # Ensure sa.orm submodule is importable
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.core.config import AuthListingsSettings
from bff_service.db.models import JobListingProjection

# Private DRY helpers


def _auth_listing_columns() -> tuple[sa.orm.InstrumentedAttribute[Any], ...]:
    """Return the column references selected for auth-listing responses.

    Centralises the column list so every query variant picks exactly the
    same projection without duplication.

    Returns:
        Tuple of SQLAlchemy mapped columns from ``JobListingProjection``.
    """
    return (
        JobListingProjection.title,
        JobListingProjection.company_name,
        JobListingProjection.location_raw,
        JobListingProjection.work_arrangement,
        JobListingProjection.required_skills,
        JobListingProjection.posted_at,
        JobListingProjection.language,
        JobListingProjection.country_code,
    )


def _quality_predicates(settings: AuthListingsSettings) -> list[sa.ColumnElement[bool]]:
    """Build reusable WHERE-clause predicates that enforce listing quality.

    Args:
        settings: Auth-listings configuration carrying age, length, and
            limit thresholds.

    Returns:
        List of SQLAlchemy binary expressions suitable for
        ``Select.where(*predicates)``.
    """
    freshness_cutoff = datetime.now(UTC) - timedelta(days=settings.max_listing_age_days)
    return [
        JobListingProjection.posted_at >= freshness_cutoff,
        JobListingProjection.title.is_not(None),
        sa.func.length(JobListingProjection.title) >= settings.min_title_length,
        JobListingProjection.company_name.is_not(None),
        JobListingProjection.company_name != "",
        JobListingProjection.country_code.is_not(None),
    ]


# Public query functions


async def fetch_primary_candidates(
    db: AsyncSession,
    country_code: str,
    settings: AuthListingsSettings,
) -> Sequence[Row[Any]]:
    """Fetch same-country listing candidates ordered by recency.

    Args:
        db: Async database session.
        country_code: ISO 3166-1 alpha-2/3 country code to match.
        settings: Auth-listings configuration for quality thresholds.

    Returns:
        Sequence of result rows containing the auth-listing column set.
    """
    stmt = (
        sa.select(*_auth_listing_columns())
        .where(*_quality_predicates(settings))
        .where(JobListingProjection.country_code == country_code)
        .order_by(JobListingProjection.posted_at.desc())
        .limit(settings.primary_candidate_limit)
    )
    return (await db.execute(stmt)).all()


async def fetch_backfill_candidates(
    db: AsyncSession,
    exclude_country: str,
    settings: AuthListingsSettings,
) -> Sequence[Row[Any]]:
    """Fetch listing candidates from all countries except *exclude_country*.

    Used when the primary same-country pool is too small and needs
    supplementing with international listings.

    Args:
        db: Async database session.
        exclude_country: Country code to exclude (the primary country).
        settings: Auth-listings configuration for quality thresholds.

    Returns:
        Sequence of result rows containing the auth-listing column set.
    """
    stmt = (
        sa.select(*_auth_listing_columns())
        .where(*_quality_predicates(settings))
        .where(JobListingProjection.country_code != exclude_country)
        .order_by(JobListingProjection.posted_at.desc())
        .limit(settings.backfill_candidate_limit)
    )
    return (await db.execute(stmt)).all()


async def fetch_global_candidates(
    db: AsyncSession,
    settings: AuthListingsSettings,
) -> Sequence[Row[Any]]:
    """Fetch listing candidates globally with no country filter.

    Used when the requested country is not recognized (not in the
    ``CountryCode`` enum) and no country-specific query is possible.

    Args:
        db: Async database session.
        settings: Auth-listings configuration for quality thresholds.

    Returns:
        Sequence of result rows containing the auth-listing column set.
    """
    stmt = (
        sa.select(*_auth_listing_columns())
        .where(*_quality_predicates(settings))
        .order_by(JobListingProjection.posted_at.desc())
        .limit(settings.primary_candidate_limit)
    )
    return (await db.execute(stmt)).all()

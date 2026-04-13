"""Mapper: DiscoveryRequest → JobSpy params, DataFrame → RawListing."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CurrencyCode,
    JobBoardSource,
    MonetaryAmount,
    PaymentFrequency,
    WorkArrangement,
)
from nohiki_observability import get_logger

from job_ingest_discovery_service.core.constraints import (
    MAX_COMPANY_NAME_LENGTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_LISTING_URL_LENGTH,
    MAX_LOCATION_RAW_LENGTH,
    MAX_TITLE_LENGTH,
    MIN_COMPANY_NAME_LENGTH,
    MIN_DESCRIPTION_LENGTH,
    MIN_LOCATION_RAW_LENGTH,
)
from job_ingest_discovery_service.core.currency import infer_currency_from_country_string
from job_ingest_discovery_service.core.models import DiscoveryLocation, DiscoveryRequest, RawListing
from job_ingest_discovery_service.providers.types import location_to_search_string

logger = get_logger(__name__)

RawJobData = dict[str, str | int | float | None]
JobSpyParams = dict[str, Any]

SITE_TO_SOURCE: dict[str, JobBoardSource] = {
    "indeed": JobBoardSource.INDEED,
    "linkedin": JobBoardSource.LINKEDIN,
    "glassdoor": JobBoardSource.GLASSDOOR,
    "zip_recruiter": JobBoardSource.ZIPRECRUITER,
    "google": JobBoardSource.GOOGLE,
}

SOURCE_TO_SITE: dict[JobBoardSource, str] = {v: k for k, v in SITE_TO_SOURCE.items()}

INTERVAL_TO_FREQUENCY: dict[str, PaymentFrequency] = {
    "yearly": PaymentFrequency.ANNUALLY,
    "monthly": PaymentFrequency.MONTHLY,
    "weekly": PaymentFrequency.WEEKLY,
    "daily": PaymentFrequency.DAILY,
    "hourly": PaymentFrequency.HOURLY,
}

SALARY_SOURCE_MAP: dict[str, CompensationSource] = {
    "direct_data": CompensationSource.EMPLOYER_PROVIDED,
    "description": CompensationSource.ESTIMATED_BY_JOB_BOARD,
}


def build_jobspy_params(request: DiscoveryRequest) -> list[JobSpyParams]:
    """Convert DiscoveryRequest to JobSpy parameter sets."""
    sites = [SOURCE_TO_SITE[s] for s in request.sources if s in SOURCE_TO_SITE] or ["indeed", "linkedin"]
    arrangements = set(request.work_arrangements)

    # Check if we should explicitly include remote/physical based on work_arrangements
    include_remote_arrangement = (
        WorkArrangement.REMOTE in arrangements or WorkArrangement.UNSPECIFIED in arrangements or not arrangements
    )
    include_physical_arrangement = not arrangements or bool(
        {WorkArrangement.ON_SITE, WorkArrangement.HYBRID, WorkArrangement.UNSPECIFIED} & arrangements
    )

    param_sets: list[JobSpyParams] = []
    for keyword in request.keywords:
        base = _base_params(keyword, sites, request.results_per_source, request.hours_old)

        # 1. Add remote-only param set if requested by arrangement OR if any location is_remote
        has_remote_location = any(loc.is_remote for loc in request.locations)
        if include_remote_arrangement or has_remote_location:
            param_sets.append(base | {"is_remote": True})

        # 2. Add physical location param sets if requested by arrangement
        if include_physical_arrangement:
            # Only include locations that are NOT purely remote
            physical_locations = [loc for loc in request.locations if not loc.is_remote]
            location_params = _location_params(base, tuple(physical_locations))
            param_sets.extend(location_params)

    if not param_sets and request.keywords:
        base = _base_params(request.keywords[0], sites, request.results_per_source, request.hours_old)
        param_sets.append(base | {"is_remote": True})

    return param_sets


def _base_params(keyword: str, sites: list[str], results: int, hours_old: int | None) -> JobSpyParams:
    """Build base JobSpy parameters.

    LinkedIn's job-card list endpoint does not include the description; without
    `linkedin_fetch_description=True` the LinkedIn scraper returns rows with
    empty descriptions. Indeed's API returns descriptions inline, so the flag
    is harmless when LinkedIn is absent.
    """
    params: JobSpyParams = {
        "site_name": sites,
        "search_term": keyword,
        "results_wanted": results,
        "linkedin_fetch_description": True,
        "description_format": "markdown",
    }
    if hours_old:
        params["hours_old"] = hours_old
    return params


def _location_params(base: JobSpyParams, locations: tuple[DiscoveryLocation, ...]) -> list[JobSpyParams]:
    """Build parameter sets for physical locations."""
    return [
        base | {"location": loc_str, "is_remote": False}
        for loc in locations
        if (loc_str := location_to_search_string(loc))
    ]


def map_dataframe_to_listings(df: pd.DataFrame) -> list[RawListing]:
    """Convert JobSpy DataFrame to RawListing internal models.

    Rows missing any required field (URL, title, company, location, or a
    description of at least ``MIN_DESCRIPTION_LENGTH`` chars) are dropped
    with a structured warning. The proto constraints on DiscoveredListing
    are mirrored here so that invalid rows are rejected at the source
    rather than at the Kafka boundary by buf.validate.
    """
    total = len(df)
    listings = [listing for _, row in df.iterrows() if (listing := _row_to_listing(_sanitize_row(row.to_dict())))]
    dropped = total - len(listings)
    if dropped:
        logger.warning(
            "Dropped listings with missing required fields",
            source="jobspy",
            total=total,
            accepted=len(listings),
            dropped=dropped,
        )
    return listings


def _row_to_listing(raw: RawJobData) -> RawListing | None:
    """Convert sanitized row to RawListing, or None if invalid.

    Rejects rows missing any of the fields required by the
    DiscoveredListing proto contract: listing_url, title, company_name
    (>=1 char), description (>=200 chars), and location_raw (>=1 char).
    The description gate also catches LinkedIn auth-wall failures where
    the scraper silently returns an empty string.
    """
    listing_url = _str(raw, "job_url") or _str(raw, "listing_url")
    title = _str(raw, "title")
    description = _str(raw, "description").strip()
    company = _str(raw, "company").strip()
    location_raw = _str(raw, "location").strip()
    site = _str(raw, "site").lower()
    source = SITE_TO_SOURCE.get(site, JobBoardSource.UNSPECIFIED)

    reason = _validation_reason(listing_url, title, description, company, location_raw)
    if reason is None and source == JobBoardSource.UNSPECIFIED:
        reason = "unknown_site"
    if reason is not None:
        logger.warning(
            "Dropping invalid listing",
            source="jobspy",
            reason=reason,
            url=listing_url,
        )
        return None

    return RawListing(
        listing_url=listing_url,
        source=source,
        title=title,
        company=company,
        description=description,
        location_raw=location_raw,
        external_id=_str(raw, "id") or None,
        posted_at=_parse_date(raw.get("date_posted")),
        apply_url=_str(raw, "job_url_direct") or None,
        company_url=_str(raw, "company_url") or None,
        compensation=_build_compensation(raw),
        logo_url=_str(raw, "company_logo") or None,
    )


def _validation_reason(
    listing_url: str,
    title: str,
    description: str,
    company: str,
    location_raw: str,
) -> str | None:
    """Return the first proto-contract violation, or None if all gates pass.

    Validates all fields against proto buf.validate constraints: min/max lengths
    for description, company_name, location_raw, title, and listing_url.
    """
    rules: list[tuple[bool, str]] = [
        (not listing_url, "missing_url"),
        (len(listing_url) > MAX_LISTING_URL_LENGTH, "url_too_long"),
        (not title, "missing_title"),
        (len(title) > MAX_TITLE_LENGTH, "title_too_long"),
        (len(description) < MIN_DESCRIPTION_LENGTH, "description_too_short"),
        (len(description) > MAX_DESCRIPTION_LENGTH, "description_too_long"),
        (len(company) < MIN_COMPANY_NAME_LENGTH, "missing_company"),
        (len(company) > MAX_COMPANY_NAME_LENGTH, "company_too_long"),
        (len(location_raw) < MIN_LOCATION_RAW_LENGTH, "missing_location"),
        (len(location_raw) > MAX_LOCATION_RAW_LENGTH, "location_too_long"),
    ]
    for condition, reason in rules:
        if condition:
            return reason
    return None


def _str(raw: RawJobData, key: str) -> str:
    """Extract string field, defaulting to empty string."""
    val = raw.get(key)
    return str(val) if val is not None else ""


def _build_compensation(raw: RawJobData) -> Compensation | None:
    """Build Compensation from JobSpy salary fields.

    Returns None if no salary data or if currency cannot be determined.
    Currency resolution order:
        1. Explicit currency field from provider
        2. Inferred from location.country field
    """
    min_val, max_val = raw.get("min_amount"), raw.get("max_amount")
    if min_val is None and max_val is None:
        return None

    currency = _resolve_currency(raw)
    if currency == CurrencyCode.UNSPECIFIED:
        return None

    frequency = INTERVAL_TO_FREQUENCY.get(_str(raw, "interval").lower(), PaymentFrequency.UNSPECIFIED)
    source = SALARY_SOURCE_MAP.get(_str(raw, "salary_source").lower(), CompensationSource.UNSPECIFIED)

    min_bound: CompensationBound | None = None
    max_bound: CompensationBound | None = None

    if min_val is not None:
        min_minor = _to_cents(min_val)
        if min_minor:
            min_bound = CompensationBound(
                amount=MonetaryAmount(minor_units=min_minor, currency=currency),
                source=source,
            )
    if max_val is not None:
        max_minor = _to_cents(max_val)
        if max_minor:
            max_bound = CompensationBound(
                amount=MonetaryAmount(minor_units=max_minor, currency=currency),
                source=source,
            )

    if min_bound is None and max_bound is None:
        return None

    compensation = Compensation(frequency=frequency)
    if min_bound is not None:
        compensation.min_amount = min_bound
    if max_bound is not None:
        compensation.max_amount = max_bound
    return compensation


def _resolve_currency(raw: RawJobData) -> CurrencyCode:
    """Resolve currency from explicit field or infer from country."""
    currency = _parse_currency(_str(raw, "currency"))
    if currency != CurrencyCode.UNSPECIFIED:
        return currency
    return infer_currency_from_country_string(_str(raw, "country"))


def _to_cents(value: str | float | None) -> int | None:
    """Convert salary value to minor currency units (cents)."""
    if value is None:
        return None
    try:
        return int(float(value) * 100)
    except ValueError, TypeError:
        return None


def _parse_currency(value: str) -> CurrencyCode:
    """Parse currency string to CurrencyCode enum."""
    if not value:
        return CurrencyCode.UNSPECIFIED
    try:
        return CurrencyCode[value.upper()]
    except KeyError:
        return CurrencyCode.UNSPECIFIED


def _parse_date(value: str | float | None) -> datetime | None:
    """Parse date string to datetime."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _sanitize_row(raw: dict[str, object]) -> RawJobData:
    """Sanitize DataFrame row values."""
    result: RawJobData = {}
    for k, v in raw.items():
        if pd.isna(v):
            result[str(k)] = None
        elif isinstance(v, datetime | date):
            result[str(k)] = v.isoformat()
        elif isinstance(v, str):
            result[str(k)] = _sanitize_text(v)
        elif isinstance(v, int | float):
            result[str(k)] = v
    return result


def _sanitize_text(text: str) -> str | None:
    """Remove problematic characters."""
    control = "".join(chr(c) for c in range(32) if c not in (9, 10, 13)) + chr(127)
    private = "".join(chr(c) for c in range(0xE000, 0xF900))
    cleaned = re.sub(r"\s+", " ", text.translate(str.maketrans("", "", control + private))).strip()
    return cleaned or None

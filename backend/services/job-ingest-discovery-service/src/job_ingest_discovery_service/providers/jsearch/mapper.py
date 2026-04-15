"""Mapper: JSearch API response → RawListing internal models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CurrencyCode,
    JobBoardSource,
    MonetaryAmount,
    PaymentFrequency,
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
from job_ingest_discovery_service.core.models import RawListing

from .models import JSearchJob, SalaryPeriod

if TYPE_CHECKING:
    from .models import JSearchResponse

logger = get_logger(__name__)

PUBLISHER_TO_SOURCE: dict[str, JobBoardSource] = {
    "indeed": JobBoardSource.INDEED,
    "linkedin": JobBoardSource.LINKEDIN,
    "glassdoor": JobBoardSource.GLASSDOOR,
    "ziprecruiter": JobBoardSource.ZIPRECRUITER,
}


SALARY_PERIOD_TO_FREQUENCY: dict[SalaryPeriod, PaymentFrequency] = {
    SalaryPeriod.YEAR: PaymentFrequency.ANNUALLY,
    SalaryPeriod.MONTH: PaymentFrequency.MONTHLY,
    SalaryPeriod.WEEK: PaymentFrequency.WEEKLY,
    SalaryPeriod.DAY: PaymentFrequency.DAILY,
    SalaryPeriod.HOUR: PaymentFrequency.HOURLY,
}


def map_response_to_listings(response: JSearchResponse) -> list[RawListing]:
    """Convert JSearch API response to RawListing internal models.

    Rows missing any field required by the DiscoveredListing proto
    contract (URL, title, company, location, description >= 200 chars)
    are dropped with a structured warning. This prevents invalid rows
    from being rejected at the Kafka boundary by buf.validate, which
    would blow up the entire discovery batch.
    """
    total = len(response.data)
    listings = [listing for job in response.data if (listing := _job_to_listing(job))]
    dropped = total - len(listings)
    if dropped:
        logger.warning(
            "Dropped listings with missing required fields",
            source="jsearch",
            total=total,
            accepted=len(listings),
            dropped=dropped,
        )
    return listings


def _job_to_listing(job: JSearchJob) -> RawListing | None:
    """Convert JSearchJob to RawListing, or None if invalid.

    Rejects rows missing any of the fields required by DiscoveredListing:
    listing_url, title, company_name (>=1 char), description (>=200
    chars), location_raw (>=1 char). For fully-remote jobs lacking a
    physical location, falls back to "Remote" so that valid remote
    postings are not dropped due to JSearch's empty-location quirk.
    """
    listing_url = job.job_google_link or job.job_apply_link or ""
    title = (job.job_title or "").strip()
    description = (job.job_description or "").strip()
    company = (job.employer_name or "").strip()
    location_raw = (job.job_location or "").strip()

    # Remote-job fallback: JSearch often returns empty job_location for
    # fully-remote postings. Synthesize "Remote" so we don't drop them.
    if not location_raw and job.job_is_remote:
        location_raw = "Remote"

    if reason := _validation_reason(listing_url, title, description, company, location_raw):
        logger.warning("Dropping invalid listing", source="jsearch", reason=reason, url=listing_url)
        return None

    # JSearch always returns a source, default to GOOGLE if no publisher match
    source = _get_source(job)

    return RawListing(
        listing_url=listing_url,
        source=source,
        title=title,
        company=company,
        description=description,
        location_raw=location_raw,
        external_id=job.job_id,
        posted_at=_parse_posted_date(job),
        apply_url=_get_apply_url(job),
        company_url=job.employer_website,
        compensation=_build_compensation(job),
        logo_url=job.employer_logo,
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


def _get_source(job: JSearchJob) -> JobBoardSource:
    """Map job publisher to JobBoardSource enum."""
    publisher = (job.job_publisher or "").lower()
    if not publisher:
        return JobBoardSource.GOOGLE

    for key, source in PUBLISHER_TO_SOURCE.items():
        if key in publisher:
            return source
    return JobBoardSource.GOOGLE


def _get_apply_url(job: JSearchJob) -> str | None:
    """Get the direct application URL if available."""
    if job.job_apply_is_direct and job.job_apply_link:
        return job.job_apply_link
    if job.apply_options:
        for option in job.apply_options:
            if option.is_direct and option.apply_link:
                return option.apply_link
    return job.job_apply_link


def _build_compensation(job: JSearchJob) -> Compensation | None:
    """Build Compensation from JSearch salary fields.

    Returns None if no salary data or if currency cannot be inferred from job_country.
    JSearch does not provide explicit currency, so we infer from job_country.
    """
    if job.job_min_salary is None and job.job_max_salary is None:
        return None

    currency = infer_currency_from_country_string(job.job_country or "")
    if currency == CurrencyCode.UNSPECIFIED:
        return None

    frequency = _resolve_frequency(job.job_salary_period)

    comp = Compensation(frequency=frequency)

    if job.job_min_salary is not None:
        comp.min_amount = CompensationBound(
            amount=MonetaryAmount(
                minor_units=int(job.job_min_salary * 100),
                currency=currency,
            ),
            source=CompensationSource.ESTIMATED_BY_JOB_BOARD,
        )

    if job.job_max_salary is not None:
        comp.max_amount = CompensationBound(
            amount=MonetaryAmount(
                minor_units=int(job.job_max_salary * 100),
                currency=currency,
            ),
            source=CompensationSource.ESTIMATED_BY_JOB_BOARD,
        )

    return comp if comp.min_amount or comp.max_amount else None


def _resolve_frequency(period: SalaryPeriod | None) -> PaymentFrequency:
    """Convert salary period to payment frequency."""
    if period is None:
        return PaymentFrequency.UNSPECIFIED
    return SALARY_PERIOD_TO_FREQUENCY.get(period, PaymentFrequency.UNSPECIFIED)


def _parse_posted_date(job: JSearchJob) -> datetime | None:
    """Parse the job posted date from JSearch data."""
    if job.job_posted_at_datetime_utc:
        return job.job_posted_at_datetime_utc
    if job.job_posted_at_timestamp:
        try:
            return datetime.fromtimestamp(job.job_posted_at_timestamp, tz=UTC)
        except OSError, OverflowError, ValueError:
            return None
    return None

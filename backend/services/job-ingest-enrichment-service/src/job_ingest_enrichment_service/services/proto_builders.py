"""Pure protobuf builders for converting EnrichmentContext to proto objects.

Stateless transformation functions with no I/O or side effects.
Used by callbacks.py to reconstruct protobuf objects from serialized context bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CountryCode,
    CurrencyCode,
    EmploymentTerm,
    ExperienceSource,
    Location,
    LocationSource,
    LocationType,
    MonetaryAmount,
    PaymentFrequency,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.job.ingest.v1 import (
    ExperienceRequirement,
    ExperienceYearsBound,
    StoredListing,
)
from nohiki.ml.v1 import EmbeddingVector
from nohiki.skill.v1 import JobSkillRequirement
from nohiki_common_exceptions import ValidationError
from nohiki_observability import get_logger

from job_ingest_enrichment_service.services._constants import MINOR_UNITS_PER_MAJOR

if TYPE_CHECKING:
    from nohiki.job.ingest.v1 import DiscoveredListing

    from job_ingest_enrichment_service.services.enrichment_context import EnrichmentContext

logger = get_logger(__name__)

COMPENSATION_SOURCE_MAP: dict[str, CompensationSource] = {
    "employer_provided": CompensationSource.EMPLOYER_PROVIDED,
    "job_board_estimate": CompensationSource.ESTIMATED_BY_JOB_BOARD,
}


@dataclass(frozen=True, slots=True)
class EmbeddingBundle:
    """All embeddings required for ECST-compliant StoredListing publication."""

    skills: EmbeddingVector
    title: EmbeddingVector
    retrieval: list[EmbeddingVector]


def map_experience_source(source: str) -> ExperienceSource:
    """Map extraction source string to proto enum."""
    return ExperienceSource.EMPLOYER_PROVIDED if source == "explicit" else ExperienceSource.INFERRED_BY_NOHIKI


def map_compensation_source(source: str) -> CompensationSource:
    """Map extraction source string to proto enum."""
    return COMPENSATION_SOURCE_MAP.get(source, CompensationSource.ESTIMATED_BY_NOHIKI)


def build_experience_bound(
    years: int,
    source: str,
    confidence: int | None,
) -> ExperienceYearsBound:
    """Build a single experience bound with source tracking."""
    bound = ExperienceYearsBound(years=years, source=map_experience_source(source))
    if source == "inferred" and confidence is not None:
        bound.confidence_percent = confidence
    return bound


def build_experience_requirement(ctx: EnrichmentContext) -> ExperienceRequirement:
    """Build ExperienceRequirement proto from context."""
    experience = ExperienceRequirement()

    if ctx.min_experience_years is not None and ctx.min_experience_source is not None:
        experience.min_years = build_experience_bound(
            ctx.min_experience_years,
            ctx.min_experience_source,
            ctx.min_experience_confidence,
        )

    if ctx.max_experience_years is not None and ctx.max_experience_source is not None:
        experience.max_years = build_experience_bound(
            ctx.max_experience_years,
            ctx.max_experience_source,
            ctx.max_experience_confidence,
        )

    return experience


def build_compensation_bound(
    amount: int,
    currency: str,
    source: str,
    confidence: int | None,
) -> CompensationBound:
    """Build a single compensation bound with source tracking."""
    bound = CompensationBound(
        amount=MonetaryAmount(minor_units=amount * MINOR_UNITS_PER_MAJOR, currency=CurrencyCode[currency]),
        source=map_compensation_source(source),
    )
    if source != "employer_provided" and confidence is not None:
        bound.confidence_percent = confidence
    return bound


def build_compensation(ctx: EnrichmentContext) -> Compensation:
    """Build Compensation proto from context."""
    return Compensation(
        min_amount=build_compensation_bound(
            ctx.compensation_min_amount,
            ctx.compensation_currency,
            ctx.compensation_min_source,
            ctx.compensation_min_confidence,
        ),
        max_amount=build_compensation_bound(
            ctx.compensation_max_amount,
            ctx.compensation_currency,
            ctx.compensation_max_source,
            ctx.compensation_max_confidence,
        ),
        frequency=PaymentFrequency[ctx.compensation_period],
    )


def build_location(ctx: EnrichmentContext) -> Location | None:
    """Build Location proto from enrichment context if location data is present.

    Args:
        ctx: Enrichment context with extracted location and work arrangement data.

    Returns:
        Location proto with country, type derived from work arrangement, or None
        if no meaningful location data was extracted.

    """
    if not ctx.location_city and ctx.location_country_code == "UNSPECIFIED":
        return None

    match ctx.work_arrangement:
        case "REMOTE":
            loc_type = LocationType.REMOTE
        case "ON_SITE" | "HYBRID":
            loc_type = LocationType.PHYSICAL
        case _:
            loc_type = LocationType.UNSPECIFIED

    return Location(
        city=ctx.location_city or "",
        state_province=ctx.location_state or "",
        country=CountryCode[ctx.location_country_code],
        location_type=loc_type,
        source=LocationSource.JOB_POSTING,
    )


def build_stored_listing_from_context(
    ctx: EnrichmentContext,
    discovered_data: DiscoveredListing,
    skill_requirements: list[JobSkillRequirement],
    embeddings: EmbeddingBundle,
) -> StoredListing:
    """Build StoredListing proto from enrichment context and skill results.

    All embedding parameters are REQUIRED - ECST compliance requires all
    embeddings computed during enrichment before publishing.
    """
    # StoredListing.location is required post-enrichment. processor_service
    # already fails fast with the same check before requesting embeddings;
    # this is defence-in-depth in case a future caller skips that path.
    location = build_location(ctx)
    if location is None:
        logger.error(
            "Late-stage location validation failed despite earlier check passing -- investigate extraction pipeline.",
            listing_url=ctx.listing_url,
            listing_id=ctx.listing_id,
            country_code=ctx.location_country_code,
        )
        raise ValidationError(
            field_name="location",
            constraint="enrichment must produce a structured Location",
            invalid_value=ctx.location_country_code,
        )

    return StoredListing(
        listing_url=ctx.listing_url,
        source=discovered_data.source,
        external_id=discovered_data.external_id,
        title=ctx.cleaned_title,
        company_name=ctx.cleaned_company,
        description=discovered_data.description,
        location=location,
        work_arrangement=WorkArrangement[ctx.work_arrangement],
        employment_term=EmploymentTerm[ctx.employment_term],
        experience=build_experience_requirement(ctx),
        seniority_level=SeniorityLevel[ctx.seniority_level],
        language=ctx.language,
        skill_requirements=skill_requirements,
        skills_embedding=embeddings.skills,
        title_embedding=embeddings.title,
        retrieval_embeddings=embeddings.retrieval,
        compensation=build_compensation(ctx),
        apply_url=discovered_data.apply_url,
        company_url=discovered_data.company_url,
        company_logo_url=discovered_data.company_logo_url,
        discovered_timestamp=discovered_data.discovered_timestamp,
        posted_timestamp=discovered_data.posted_timestamp,
        stored_timestamp=datetime.now(UTC),
        content_hash=discovered_data.content_hash,
        version=1,
    )

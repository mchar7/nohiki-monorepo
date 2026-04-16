"""Job enrichment processor service using LLM and skill normalization.

Uses Request/Callback pattern with context-carried state (ECST compliant).
NO database saga - context bytes carry all state through the callback.

Flow:
1. Receive ListingAccepted with DiscoveredListing
2. Run PydanticAI extraction (synchronous)
3. Build EnrichmentContext with ALL extraction results
4. Publish SkillNormalizationRequested with context
5. Return immediately - callback handler completes the flow
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nohiki.common.v1 import CommandHeader, CompensationSource, CountryCode, Location
from nohiki.skill.v1 import RawSkillWithLevel, SkillNormalizationRequested, SkillProficiencyLevel
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import create_event_metadata
from nohiki_geo_utils import geocode_location
from nohiki_kafka_client import Topics
from nohiki_observability import get_logger
from uuid_utils.compat import uuid7

from job_ingest_enrichment_service.core.config import get_settings
from job_ingest_enrichment_service.core.kafka import kafka_client
from job_ingest_enrichment_service.metrics import get_job_enrichment_metrics
from job_ingest_enrichment_service.services._constants import MINOR_UNITS_PER_MAJOR
from job_ingest_enrichment_service.services.compensation_builder import CompensationBuilder
from job_ingest_enrichment_service.services.enrichment_context import EnrichmentContext
from job_ingest_enrichment_service.services.extraction_agent import run_extraction_agent

if TYPE_CHECKING:
    from nohiki.common.v1 import ListingReference
    from nohiki.job.ingest.v1 import DiscoveredListing

logger = get_logger(__name__)


def _comp_source_to_ctx(source: CompensationSource) -> str:
    """Map proto CompensationSource enum to enrichment context source string."""
    match source:
        case CompensationSource.EMPLOYER_PROVIDED:
            return "employer_provided"
        case CompensationSource.ESTIMATED_BY_JOB_BOARD:
            return "job_board_estimate"
        case _:
            return "llm_inferred"


async def process_job_enrichment(
    discovered_data: DiscoveredListing,
    listing_reference: ListingReference,
    correlation_id: str,
) -> dict[str, str] | None:
    """Process discovered job data using LLM extraction and request skill normalization.

    This function:
    1. Runs PydanticAI extraction to get structured job data
    2. Builds compensation from best available source
    3. Creates EnrichmentContext with all extraction results
    4. Publishes SkillNormalizationRequested with context bytes
    5. Returns immediately - callback handler completes the flow

    Args:
        discovered_data: Typed DiscoveredListing from scraper
        listing_reference: Reference to the listing being processed
        correlation_id: Correlation ID for tracing

    Returns:
        Dict with extracted title and company if successful, None otherwise

    """
    description_length = len(discovered_data.description or "")
    max_description_length = get_settings().processing.max_listing_description_chars
    if description_length > max_description_length:
        raise ValidationError(
            field_name="discovered_data.description",
            invalid_value=f"len={description_length}",
            constraint=f"length <= {max_description_length}",
        )

    start_time = time.perf_counter()
    metrics = get_job_enrichment_metrics()
    metrics.record_pipeline_stage("accepted")

    llm_result = await run_extraction_agent(discovered_data)
    extraction = llm_result.output

    # Fail fast before any embedding work: if extraction produced no usable
    # location, downstream proto construction would raise after 3 round-trips
    # to ml-compute. Route directly to DLQ instead.
    if not extraction.location.city and extraction.location.country_code == CountryCode.UNSPECIFIED:
        raise ValidationError(
            field_name="location",
            constraint="enrichment must produce a structured Location",
            invalid_value=extraction.location.country_code.name,
        )

    # Build compensation from best available source (employer-provided > job board > LLM)
    best_comp = CompensationBuilder().build(discovered_data, extraction.compensation_estimate)

    # Extract context-compatible compensation fields from the builder's chosen proto.
    # Amounts convert from minor_units (proto) to major units (context).
    min_b = best_comp.min_amount
    max_b = best_comp.max_amount

    location_proto = Location(
        city=extraction.location.city or "",
        state_province=extraction.location.state_province or "",
        country=extraction.location.country_code,
    )
    geocoded_location = await geocode_location(location_proto)

    geocoded_lat: float | None = None
    geocoded_lon: float | None = None
    if geocoded_location.coordinates:
        geocoded_lat = geocoded_location.coordinates.latitude
        geocoded_lon = geocoded_location.coordinates.longitude

    # Extract experience bounds with per-bound source tracking
    exp = extraction.experience
    min_exp = exp.min_years
    max_exp = exp.max_years

    # Compensation - per-bound source tracking from best available source
    if min_b and min_b.amount.minor_units:
        comp_currency = min_b.amount.currency.name
    elif max_b:
        comp_currency = max_b.amount.currency.name
    else:
        comp_currency = None

    context = EnrichmentContext(
        listing_id=listing_reference.listing_id or "",
        listing_url=listing_reference.listing_url,
        correlation_id=correlation_id,
        discovered_json=discovered_data.to_json(),
        cleaned_title=extraction.cleaned_title,
        cleaned_company=extraction.cleaned_company,
        work_arrangement=extraction.work_arrangement.name,
        employment_term=extraction.employment_term.name,
        seniority_level=extraction.seniority_level.name,
        language=extraction.language,
        # Experience - per-bound source tracking
        min_experience_years=min_exp.years if min_exp else None,
        min_experience_source=min_exp.source if min_exp else None,
        min_experience_confidence=min_exp.confidence_percent if min_exp else None,
        max_experience_years=max_exp.years if max_exp else None,
        max_experience_source=max_exp.source if max_exp else None,
        max_experience_confidence=max_exp.confidence_percent if max_exp else None,
        # Compensation - per-bound source tracking from builder's chosen source
        compensation_min_amount=min_b.amount.minor_units // MINOR_UNITS_PER_MAJOR if min_b else 0,
        compensation_min_source=_comp_source_to_ctx(min_b.source) if min_b else "",
        compensation_min_confidence=min_b.confidence_percent or None if min_b else None,
        compensation_max_amount=max_b.amount.minor_units // MINOR_UNITS_PER_MAJOR if max_b else 0,
        compensation_max_source=_comp_source_to_ctx(max_b.source) if max_b else "",
        compensation_max_confidence=max_b.confidence_percent or None if max_b else None,
        compensation_currency=comp_currency or "",
        compensation_period=best_comp.frequency.name,
        compensation_reasoning=extraction.compensation_estimate.reasoning,
        location_city=extraction.location.city,
        location_state=extraction.location.state_province,
        location_country_code=extraction.location.country_code.name,
        raw_skill_required_map={s.raw_skill.lower(): s.relation_type == "essential" for s in extraction.skills},
        geocoded_lat=geocoded_lat,
        geocoded_lon=geocoded_lon,
    )

    if any(s.skill_type or s.reuse_level or s.years_experience or s.source != "explicit" for s in extraction.skills):
        logger.warning(
            "Discarding ESCO classifications until skill-graph proto adds hint fields",
            skill_count=len(extraction.skills),
            types_present=sum(bool(s.skill_type) for s in extraction.skills),
            sources_inferred=sum(s.source == "inferred" for s in extraction.skills),
            years_present=sum(s.years_experience is not None for s in extraction.skills),
            correlation_id=correlation_id,
        )

    # RawSkillWithLevel proto carries only raw_skill + is_required + proficiency_level
    # today. ESCO skill_type/reuse_level and provenance (explicit vs inferred) and
    # years_experience from ExtractedSkill are logged for telemetry above and not
    # propagated to skill-graph until the proto carries hint fields.
    raw_skills_with_levels = [
        RawSkillWithLevel(
            raw_skill=s.raw_skill,
            proficiency_level=SkillProficiencyLevel.UNSPECIFIED,
            is_required=s.relation_type == "essential",
        )
        for s in extraction.skills
    ]

    await _request_skill_normalization(
        context=context,
        raw_skills_with_levels=raw_skills_with_levels,
    )

    duration_seconds = time.perf_counter() - start_time
    metrics.record_saga_completion("enrichment", duration_seconds, success=True)
    metrics.record_pipeline_stage("enriched")

    logger.info(
        "Job enrichment initiated",
        listing_url=listing_reference.listing_url,
        title=extraction.cleaned_title,
        seniority=extraction.seniority_level.name,
        skill_count=len(raw_skills_with_levels),
        correlation_id=correlation_id,
    )

    return {
        "title": extraction.cleaned_title,
        "company": extraction.cleaned_company,
    }


async def _request_skill_normalization(
    context: EnrichmentContext,
    raw_skills_with_levels: list[RawSkillWithLevel],
) -> None:
    """Request skill normalization with context carrying all state."""
    settings = get_settings()
    request_id = str(uuid7())

    skill_request = SkillNormalizationRequested(
        metadata=create_event_metadata(settings.service_name, context.correlation_id),
        command=CommandHeader(
            operation_id=request_id,
            callback_topic=Topics.JOB_INGEST_SKILL_CALLBACK,
            caller_context=context.to_bytes(),
        ),
        raw_skills=[s.raw_skill for s in raw_skills_with_levels],
        raw_skills_with_levels=raw_skills_with_levels,
    )
    await kafka_client.publish(Topics.SKILL_NORMALIZATION_REQUESTED, skill_request)

    logger.info(
        "Skill normalization requested",
        operation_id=request_id,
        skill_count=len(raw_skills_with_levels),
        listing_url=context.listing_url,
        correlation_id=context.correlation_id,
    )

"""Common builders for centralized sample-data personas."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CountryCode,
    CurrencyCode,
    EntityTimestamps,
    EventMetadata,
    ExperiencePreference,
    FeatureImportancePrefs,
    JobBoardSource,
    Location,
    LocationPrecision,
    LocationSource,
    LocationType,
    MonetaryAmount,
    NotificationChannel,
    NotificationFrequency,
    NotificationMethod,
    PaymentFrequency,
    SalaryPreference,
    SearchPrefNotificationConfig,
)
from nohiki.job.ingest.v1 import DiscoveredListing
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki.skill.v1 import JobSkillRequirement, SkillProficiencyLevel, SkillProvenance, UserSkillEntry
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_domain_utils.threshold_constants import (
    DEFAULT_AUTO_TAILOR_THRESHOLD,
    DEFAULT_NOTIFICATION_THRESHOLD,
)

from ._ids import FIXED_TIMESTAMP
from ._types import ListingPersonaSpec, PrefPersonaSpec

# Embedding configuration
DEFAULT_EMBEDDING_DIMS: int = 8
SAMPLE_DATA_MODEL_ID: str = "sample-data-deterministic-v1"
COLLECTION_VERSION: str = "v1"
EVENT_METADATA_VERSION: str = "v1"

# Confidence scores for generated skill data
SKILL_EXTRACTION_CONFIDENCE: float = 0.92
SKILL_PROVENANCE_CONFIDENCE: float = 0.95

# Default feature importance weights (out of 100)
DEFAULT_SKILL_MATCH_IMPORTANCE: int = 85
DEFAULT_LOCATION_IMPORTANCE: int = 65
DEFAULT_WORK_ARRANGEMENT_IMPORTANCE: int = 75
DEFAULT_EXPERIENCE_IMPORTANCE: int = 60
DEFAULT_SALARY_IMPORTANCE: int = 70
DEFAULT_RECENCY_IMPORTANCE: int = 40

# Default preference thresholds
DEFAULT_MIN_FIT_SCORE_DISQUALIFY: int = 40


def stable_uuid(seed: str) -> str:
    """Return deterministic UUIDv5 for the given seed."""
    return str(uuid5(NAMESPACE_URL, seed))


def make_raw_content_hash(seed: str) -> str:
    """Create deterministic SHA-256 hex digest for persona payloads."""
    return sha256(seed.encode("utf-8")).hexdigest()


def make_location(
    city: str | None,
    state_province: str | None,
    *,
    country: CountryCode = CountryCode.USA,
    location_type: LocationType = LocationType.PHYSICAL,
) -> Location:
    """Build a normalized physical location object."""
    return Location(
        city=city,
        state_province=state_province,
        country=country,
        location_type=location_type,
        precision=LocationPrecision.CITY_CENTER,
        source=LocationSource.JOB_POSTING,
    )


def format_location_raw(location: Location) -> str:
    """Render a Location as a human-readable scrape-style string for fixtures.

    Used by sample-data builders that need to round-trip a structured Location
    back into the unparsed `location_raw` form expected by DiscoveredListing
    and other pre-enrichment representations.

    Intentionally duplicated with bff-service's ``format_location_display``:
    test-utils cannot depend on a downstream service, and the projection
    helper cannot depend on test-utils. The rendering rule (``city, state``
    or ``"Remote"``) is a stable display contract kept in sync by hand.
    """
    parts = [p for p in (location.city, location.state_province) if p]
    if parts:
        return ", ".join(parts)
    if location.location_type == LocationType.REMOTE:
        return "Remote"
    if location.country:
        return location.country.name
    return ""


def make_remote_location(*, country: CountryCode = CountryCode.USA) -> Location:
    """Build a remote work location without physical city/state."""
    return Location(
        city=None,
        state_province=None,
        country=country,
        location_type=LocationType.REMOTE,
        precision=LocationPrecision.UNSPECIFIED,
        source=LocationSource.JOB_POSTING,
    )


def make_monetary_amount(
    minor_units: int,
    *,
    currency: CurrencyCode = CurrencyCode.USD,
) -> MonetaryAmount:
    """Build a monetary amount in minor units."""
    return MonetaryAmount(minor_units=minor_units, currency=currency)


def make_compensation_bound(
    minor_units: int,
    *,
    currency: CurrencyCode = CurrencyCode.USD,
    source: CompensationSource = CompensationSource.EMPLOYER_PROVIDED,
) -> CompensationBound:
    """Build a compensation bound with source metadata."""
    return CompensationBound(
        amount=make_monetary_amount(minor_units, currency=currency),
        source=source,
    )


def make_compensation_range(
    min_minor_units: int,
    max_minor_units: int,
    *,
    currency: CurrencyCode = CurrencyCode.USD,
    source: CompensationSource = CompensationSource.EMPLOYER_PROVIDED,
    frequency: PaymentFrequency = PaymentFrequency.ANNUALLY,
) -> Compensation:
    """Build compensation range with deterministic bounds."""
    return Compensation(
        min_amount=make_compensation_bound(min_minor_units, currency=currency, source=source),
        max_amount=make_compensation_bound(max_minor_units, currency=currency, source=source),
        frequency=frequency,
    )


def make_embedding(
    seed: str,
    *,
    embedding_type: EmbeddingType = EmbeddingType.DENSE,
    dims: int = DEFAULT_EMBEDDING_DIMS,
) -> EmbeddingVector:
    """Build deterministic embedding vectors for persona snapshots."""
    digest = sha256(seed.encode("utf-8")).digest()
    values = [round((digest[i % len(digest)] / 255.0) * 2.0 - 1.0, 6) for i in range(dims)]
    return EmbeddingVector(
        embedding_type=embedding_type,
        dense=DenseData(values=values),
        content_hash=make_raw_content_hash(seed),
        model_id=SAMPLE_DATA_MODEL_ID,
        collection_version=COLLECTION_VERSION,
    )


def make_skill_requirements(skills: list[str]) -> list[JobSkillRequirement]:
    """Build canonical skill requirement payloads from plain skill names."""
    return [
        JobSkillRequirement(
            skill_id=stable_uuid(f"listing-skill:{skill.lower()}"),
            skill_name=skill,
            proficiency_level=SkillProficiencyLevel.INTERMEDIATE,
            is_required=True,
            extraction_confidence=SKILL_EXTRACTION_CONFIDENCE,
        )
        for skill in skills
    ]


def make_user_skills(skills: list[str]) -> list[UserSkillEntry]:
    """Build user skill entries from plain skill names."""
    return [
        UserSkillEntry(
            skill_id=stable_uuid(f"user-skill:{skill.lower()}"),
            skill_name=skill,
            proficiency=SkillProficiencyLevel.ADVANCED,
            provenance=SkillProvenance.USER_DECLARED,
            provenance_confidence=SKILL_PROVENANCE_CONFIDENCE,
            declared_at=FIXED_TIMESTAMP,
            last_verified_at=FIXED_TIMESTAMP,
        )
        for skill in skills
    ]


def make_entity_timestamps(*, at: datetime = FIXED_TIMESTAMP) -> EntityTimestamps:
    """Build entity timestamps used by snapshot messages."""
    return EntityTimestamps(created_at=at, updated_at=at)


def make_notification_config() -> SearchPrefNotificationConfig:
    """Build a default per-preference notification configuration."""
    return SearchPrefNotificationConfig(
        threshold=DEFAULT_NOTIFICATION_THRESHOLD,
        frequency=NotificationFrequency.DAILY,
        methods=[
            NotificationMethod(
                enabled=True,
                channel=NotificationChannel.EMAIL,
            )
        ],
    )


def build_listing_snapshot(spec: ListingPersonaSpec) -> ListingSnapshot:
    """Build a complete listing snapshot with embeddings and skill requirements."""
    return ListingSnapshot(
        id=spec.entity_id,
        listing_url=spec.listing_url,
        source=spec.source,
        title=spec.title,
        company_name=spec.company_name,
        description=spec.description,
        location=spec.location,
        work_arrangement=spec.work_arrangement,
        seniority_level=spec.seniority_level,
        required_skills=spec.required_skills,
        experience_years_min=spec.experience_years_min,
        experience_years_max=spec.experience_years_max,
        compensation=spec.compensation,
        posted_at=FIXED_TIMESTAMP,
        discovered_at=FIXED_TIMESTAMP,
        processed_at=FIXED_TIMESTAMP,
        created_at=FIXED_TIMESTAMP,
        updated_at=FIXED_TIMESTAMP,
        version=spec.version,
        raw_content_hash=make_raw_content_hash(f"{spec.entity_id}:{spec.title}:{spec.company_name}"),
        skill_requirements=make_skill_requirements(spec.required_skills),
        skills_embedding=make_embedding(f"{spec.entity_id}:skills", embedding_type=EmbeddingType.DENSE),
        title_embedding=make_embedding(f"{spec.entity_id}:title", embedding_type=EmbeddingType.DENSE),
        collection_version=COLLECTION_VERSION,
        retrieval_embeddings=[make_embedding(f"{spec.entity_id}:retrieval", embedding_type=EmbeddingType.MUVERA)],
    )


def build_search_pref_snapshot(spec: PrefPersonaSpec) -> SearchPrefSnapshot:
    """Build complete preference snapshot used by integration and ML tests."""
    return SearchPrefSnapshot(
        id=spec.entity_id,
        user_id=spec.user_id,
        pref_name=spec.pref_name,
        search_keywords=spec.search_keywords,
        disallowed_keywords=spec.disallowed_keywords,
        physical_locations=spec.physical_locations,
        remote_locations=spec.remote_locations,
        work_arrangements=spec.work_arrangements,
        open_to_relocation=spec.open_to_relocation,
        experience_preference=ExperiencePreference(
            experience_years=spec.experience_years,
            seniority_levels=spec.seniority_levels,
        ),
        salary_preference=SalaryPreference(
            min_salary=make_monetary_amount(spec.min_salary_minor_units),
            target_salary=make_monetary_amount(spec.target_salary_minor_units),
            preferred_frequency=PaymentFrequency.ANNUALLY,
        ),
        feature_importance=FeatureImportancePrefs(
            skill_match_importance=DEFAULT_SKILL_MATCH_IMPORTANCE,
            location_importance=DEFAULT_LOCATION_IMPORTANCE,
            work_arrangement_importance=DEFAULT_WORK_ARRANGEMENT_IMPORTANCE,
            experience_importance=DEFAULT_EXPERIENCE_IMPORTANCE,
            salary_importance=DEFAULT_SALARY_IMPORTANCE,
            recency_importance=DEFAULT_RECENCY_IMPORTANCE,
        ),
        scrape_sources=[JobBoardSource.LINKEDIN, JobBoardSource.INDEED],
        excluded_scrape_sources=[],
        min_fit_score_disqualify=DEFAULT_MIN_FIT_SCORE_DISQUALIFY,
        auto_tailor_threshold=DEFAULT_AUTO_TAILOR_THRESHOLD,
        tailoring_preferences={},
        user_skills=make_user_skills(spec.user_skill_names),
        user_skills_embedding=make_embedding(f"{spec.entity_id}:user-skills", embedding_type=EmbeddingType.DENSE),
        query_embedding=make_embedding(f"{spec.entity_id}:query", embedding_type=EmbeddingType.DENSE),
        query_retrieval_embeddings=[
            make_embedding(f"{spec.entity_id}:query-retrieval", embedding_type=EmbeddingType.MUVERA)
        ],
        is_active=True,
        example_uploads=[],
        context_uploads=[],
        timestamps=make_entity_timestamps(),
        notification_config=make_notification_config(),
    )


def to_discovered_listing(
    snapshot: ListingSnapshot,
    *,
    external_id: str | None = None,
) -> DiscoveredListing:
    """Convert a listing snapshot persona into discovered-listing input format."""
    return DiscoveredListing(
        listing_url=snapshot.listing_url,
        source=snapshot.source,
        external_id=external_id or snapshot.id,
        title=snapshot.title,
        company_name=snapshot.company_name,
        description=snapshot.description,
        location_raw=format_location_raw(snapshot.location),
        raw_skills=list(snapshot.required_skills),
        compensation=snapshot.compensation,
        apply_url=snapshot.listing_url,
        company_url=None,
        discovered_timestamp=snapshot.discovered_at,
        posted_timestamp=snapshot.posted_at or snapshot.discovered_at,
        content_hash=snapshot.raw_content_hash,
    )


def make_event_metadata(
    *,
    event_id: str,
    source_service: str,
    correlation_id: str,
) -> EventMetadata:
    """Build deterministic event metadata for pre-composed event fixtures."""
    return EventMetadata(
        event_id=event_id,
        timestamp=FIXED_TIMESTAMP,
        source_service=source_service,
        correlation_id=correlation_id,
        version=EVENT_METADATA_VERSION,
    )

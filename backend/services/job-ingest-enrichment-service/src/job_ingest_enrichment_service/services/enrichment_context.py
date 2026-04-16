"""Enrichment context for Request/Callback pattern.

This dataclass is serialized to bytes and passed in the `context` field of
SkillNormalizationRequested. When SkillNormalizationCompleted arrives,
context is echoed back - we deserialize and continue processing.

NO DATABASE TABLE NEEDED for intermediate state.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class EnrichmentContext:
    """All state needed to complete enrichment after skill normalization.

    Serialized to bytes → passed in proto context field → echoed back.
    """

    listing_id: str
    listing_url: str
    correlation_id: str

    discovered_json: str

    cleaned_title: str
    cleaned_company: str

    work_arrangement: str
    employment_term: str
    seniority_level: str
    language: str  # IETF BCP 47 language tag (e.g. "en", "fr-CA", "zh-CN")

    # Experience - per-bound source tracking (None if bound not present)
    min_experience_years: int | None
    min_experience_source: str | None  # "explicit" or "inferred"
    min_experience_confidence: int | None  # Only for inferred
    max_experience_years: int | None
    max_experience_source: str | None
    max_experience_confidence: int | None

    # Compensation - per-bound source tracking
    # Amounts are in MAJOR UNITS (whole currency units). Conversion to minor_units
    # happens in proto_builders.build_compensation_bound via _MINOR_UNITS_PER_MAJOR.
    compensation_min_amount: int
    compensation_min_source: str  # "employer_provided", "job_board_estimate", "llm_inferred"
    compensation_min_confidence: int | None
    compensation_max_amount: int
    compensation_max_source: str
    compensation_max_confidence: int | None
    compensation_currency: str
    compensation_period: str
    compensation_reasoning: str

    location_city: str | None
    location_state: str | None
    location_country_code: str

    # Map of raw_skill name (lowercased) -> is_required, captured at extraction
    # time. Used by the skill-callback fallback path so we don't have to
    # fabricate is_required when skill-graph returns raw results without an
    # is_required field.
    raw_skill_required_map: dict[str, bool] = field(default_factory=dict)

    geocoded_lat: float | None = None
    geocoded_lon: float | None = None

    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_bytes(self) -> bytes:
        """Serialize to bytes for proto context field."""
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> EnrichmentContext:
        """Deserialize from proto context field, ignoring unknown fields from stale messages."""
        parsed = json.loads(data.decode("utf-8"))
        valid_field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in parsed.items() if k in valid_field_names}
        return cls(**filtered)

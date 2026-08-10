"""Domain models and results for job matching."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nohiki.common.v1 import CorrelationStatus
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from uuid_utils.compat import uuid7

from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import FactorAttribution


@dataclass(frozen=True, slots=True)
class JobMatchResult:
    """Result of a job match evaluation."""

    pref_id: str
    listing_id: str
    listing_url: str
    score: int
    feature_schema_version: str
    role_relevance_raw: float
    ranking_index: float
    factors: tuple[FactorAttribution, ...]
    feature_vector: tuple[float, ...] | None = None
    correlation_id: uuid.UUID = field(default_factory=uuid7)
    status: CorrelationStatus = CorrelationStatus.EVALUATED
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class MatchContext:
    """Context data for job matching operations."""

    listing_id: str
    listing_url: str
    job: ListingSnapshot
    profile: SearchPrefSnapshot
    correlation_id: str

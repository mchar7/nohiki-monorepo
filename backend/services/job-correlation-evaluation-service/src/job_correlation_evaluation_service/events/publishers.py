"""Transactional WAL publishers for correlation events."""

import json
from typing import TYPE_CHECKING, Final

from nohiki.common.v1 import UploadReference
from nohiki.job.correlation.v1 import (
    CorrelationEvaluated,
    FitFactor,
    FitFactorContribution,
    FitRankingBreakdown,
)
from nohiki.job.listing.v1 import ListingNotificationSnapshot, ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger
from sqlalchemy import text

from job_correlation_evaluation_service.core.config import get_settings
from job_correlation_evaluation_service.services.match_types import (
    JobMatchResult,
    MatchContext,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()

AGGREGATE_TYPE: Final[str] = "correlation"
FIT_RANKING_METHOD_VERSION: Final[str] = "deterministic-fit-v1"
_EMIT_TRANSACTIONAL_WAL = text("SELECT pg_logical_emit_message(true, CAST(:prefix AS text), CAST(:content AS bytea))")
_FIT_FACTORS: Final[dict[str, FitFactor]] = {
    "skills": FitFactor.SKILLS,
    "location": FitFactor.LOCATION,
    "work_arrangement": FitFactor.WORK_ARRANGEMENT,
    "experience": FitFactor.EXPERIENCE,
    "salary": FitFactor.SALARY,
    "recency": FitFactor.RECENCY,
}


def _build_fit_ranking_breakdown(result: JobMatchResult) -> FitRankingBreakdown:
    """Build the versioned, human-facing deterministic ranking explanation."""
    factors = [
        FitFactorContribution(
            factor=FitFactor.ROLE_RELEVANCE,
            compatibility_score=result.role_relevance_raw,
            importance=100,
            contribution_points=result.role_relevance_raw,
        )
    ]
    factors.extend(
        FitFactorContribution(
            factor=_FIT_FACTORS[attribution.name],
            compatibility_score=100.0 * attribution.compatibility,
            importance=attribution.importance,
            contribution_points=attribution.contribution_points,
        )
        for attribution in result.factors
    )
    return FitRankingBreakdown(method_version=FIT_RANKING_METHOD_VERSION, factors=factors)


def _serialize_correlation_metadata(result: JobMatchResult) -> dict[str, str]:
    """Serialize the legacy metadata map as empty until typed attribution exists."""
    del result
    return {}


def _build_listing_notification_snapshot(
    job: ListingSnapshot,
) -> ListingNotificationSnapshot:
    """Build minimal listing snapshot for notification downstream consumers.

    Extracts only fields needed for notification rendering. The structured
    Location flows through verbatim; downstream services format it for the
    target medium (email, push, etc.).

    Args:
        job: Full listing snapshot from ECST event.

    Returns:
        Minimal snapshot with notification-relevant fields.

    """
    snapshot = ListingNotificationSnapshot(
        id=str(job.id),
        listing_url=job.listing_url,
        title=job.title or "Untitled",
        company_name=job.company_name or "",
        location=job.location,
    )
    if job.posted_at:
        snapshot.posted_at = job.posted_at
    return snapshot


def _collect_pref_uploads(pref_snapshot: SearchPrefSnapshot) -> list[UploadReference]:
    """Collect all upload references from preference snapshot.

    Args:
        pref_snapshot: User preference snapshot with upload references.

    Returns:
        Combined list of example and context uploads.

    """
    uploads: list[UploadReference] = []
    uploads.extend(list(pref_snapshot.example_uploads))
    uploads.extend(list(pref_snapshot.context_uploads))
    return uploads


async def publish_correlation_evaluated(
    db: AsyncSession,
    result: JobMatchResult,
    context: MatchContext,
) -> None:
    """Emit CorrelationEvaluated atomically in the caller's transaction.

    The transactional logical message is committed with its correlation row;
    Debezium cannot observe either side independently.
    """
    listing_snapshot = _build_listing_notification_snapshot(context.job)
    pref_uploads = _collect_pref_uploads(context.profile)

    metadata = create_event_metadata(settings.service_name, context.correlation_id)
    event = CorrelationEvaluated(
        metadata=metadata,
        correlation_id=str(result.correlation_id),
        fit_score=result.score,
        correlation_status=result.status,
        correlation_metadata=_serialize_correlation_metadata(result),
        fit_ranking_breakdown=_build_fit_ranking_breakdown(result),
        listing_snapshot=listing_snapshot,
        pref_snapshot=context.profile,
        pref_uploads=pref_uploads,
    )

    prefix = json.dumps(
        {
            "id": str(metadata.event_id),
            "topic": Topics.JOB_CORRELATION_EVALUATED,
            "aggregate_id": str(result.correlation_id),
            "aggregate_type": AGGREGATE_TYPE,
            "correlation_id": context.correlation_id or None,
        },
        separators=(",", ":"),
    )
    await db.execute(_EMIT_TRANSACTIONAL_WAL, {"prefix": prefix, "content": bytes(event)})

    logger.debug(
        "Emitted CORRELATION_EVALUATED to transactional WAL",
        correlation_id=str(result.correlation_id),
        pref_id=str(result.pref_id),
        listing_id=str(result.listing_id),
    )

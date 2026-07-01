"""Job correlation domain projection handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy.dialects.postgresql import insert

from bff_service.core.kafka import kafka_client
from bff_service.db.models import JobCorrelationProjection
from bff_service.events.projections._constants import projection_priority_group_id
from bff_service.events.projections._helpers import (
    format_location_display,
    normalize_correlation_status,
)


def _serialize_fit_ranking_breakdown(
    message: CorrelationEvaluated,
) -> dict[str, object] | None:
    breakdown = message.fit_ranking_breakdown
    if breakdown is None:
        return None
    return {
        "method_version": breakdown.method_version,
        "factors": [
            {
                "factor": contribution.factor.name,
                "compatibility_score": contribution.compatibility_score,
                "importance": contribution.importance,
                "contribution_points": contribution.contribution_points,
            }
            for contribution in breakdown.factors
        ],
    }


logger = get_logger(__name__)


@kafka_client.message_handler(
    Topics.JOB_CORRELATION_EVALUATED,
    CorrelationEvaluated,
    group_id=projection_priority_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_correlation_evaluated(message: CorrelationEvaluated, context: MessageContext) -> None:
    """Handle job correlation evaluated event - create projection for user's job matches."""
    listing_snapshot = message.listing_snapshot
    pref_snapshot = message.pref_snapshot

    if listing_snapshot is None:
        logger.warning("CorrelationEvaluated missing listing_snapshot")
        return
    if pref_snapshot is None:
        logger.warning("CorrelationEvaluated missing pref_snapshot")
        return

    now = datetime.now(UTC)
    correlation_id = UUID(message.correlation_id)
    user_id = UUID(pref_snapshot.user_id)
    pref_id = UUID(pref_snapshot.id)
    listing_id = UUID(listing_snapshot.id)
    status = normalize_correlation_status(message.correlation_status)
    score_breakdown: dict[str, str] = {}
    fit_ranking_breakdown = _serialize_fit_ranking_breakdown(message)
    serialized_pref_snapshot = pref_snapshot.to_dict()
    serialized_pref_uploads = [upload.to_dict() for upload in message.pref_uploads]

    session = context.require_db_session()
    stmt = (
        insert(JobCorrelationProjection)
        .values(
            id=correlation_id,
            user_id=user_id,
            pref_id=pref_id,
            listing_id=listing_id,
            fit_score=message.fit_score,
            status=status,
            score_breakdown=score_breakdown,
            fit_ranking_breakdown=fit_ranking_breakdown,
            pref_snapshot=serialized_pref_snapshot,
            pref_uploads=serialized_pref_uploads,
            listing_title=listing_snapshot.title,
            listing_company=listing_snapshot.company_name or None,
            listing_url=listing_snapshot.listing_url,
            listing_location=format_location_display(listing_snapshot.location) or None,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_correlation_pref_listing",
            set_={
                "id": correlation_id,
                "user_id": user_id,
                "listing_title": listing_snapshot.title,
                "listing_company": listing_snapshot.company_name or None,
                "listing_url": listing_snapshot.listing_url,
                "listing_location": format_location_display(listing_snapshot.location) or None,
                "fit_score": message.fit_score,
                "status": status,
                "score_breakdown": score_breakdown,
                "fit_ranking_breakdown": fit_ranking_breakdown,
                "pref_snapshot": serialized_pref_snapshot,
                "pref_uploads": serialized_pref_uploads,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    logger.info(
        "Job correlation projection created/updated",
        correlation_id=str(correlation_id),
        user_id=str(user_id),
        fit_score=message.fit_score,
    )

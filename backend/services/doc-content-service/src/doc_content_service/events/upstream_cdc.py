"""Upstream CDC handlers for doc-content-service - handles job correlation events."""

from __future__ import annotations

from nohiki.job.correlation.v1 import CorrelationEvaluated
from nohiki_common_exceptions import ValidationError
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from doc_content_service.core.config import get_settings
from doc_content_service.core.kafka import kafka_client

logger = get_logger(__name__)
settings = get_settings()
primary_group_id = settings.kafka.consumer_group

DEFAULT_AUTO_GENERATION_THRESHOLD = 80


@kafka_client.message_handler(Topics.JOB_CORRELATION_EVALUATED, CorrelationEvaluated, group_id=primary_group_id)
async def handle_job_matched(message: CorrelationEvaluated, _context: MessageContext) -> None:
    """Handle job matched events for auto-generation eligibility check."""
    pref_snapshot = message.pref_snapshot
    listing_snapshot = message.listing_snapshot
    metadata = message.metadata

    if pref_snapshot is None:
        raise ValidationError(
            field_name="pref_snapshot",
            constraint="CorrelationEvaluated must carry pref_snapshot for content generation",
        )
    if listing_snapshot is None:
        raise ValidationError(
            field_name="listing_snapshot",
            constraint="CorrelationEvaluated must carry listing_snapshot for content generation",
        )

    pref_id = pref_snapshot.id
    listing_id = listing_snapshot.id
    correlation_score = message.fit_score

    logger.info(
        "Received job matched event for content generation",
        pref_id=pref_id,
        listing_id=listing_id,
        correlation_score=correlation_score,
        correlation_id=metadata.correlation_id,
    )

    threshold = pref_snapshot.auto_tailor_threshold or DEFAULT_AUTO_GENERATION_THRESHOLD
    if correlation_score >= threshold:
        # Auto-generation trigger is intentionally unimplemented: the command
        # surface for resume/cover-letter generation has not been wired to
        # this consumer yet. Log at WARNING so missed eligibility decisions
        # surface in dashboards rather than disappearing silently.
        logger.warning(
            "Auto-generation eligible correlation observed but trigger is not implemented",
            pref_id=pref_id,
            listing_id=listing_id,
            correlation_score=correlation_score,
            threshold=threshold,
            correlation_id=metadata.correlation_id,
        )

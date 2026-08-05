"""Kafka handler for backfill listing responses."""

import json
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from nohiki.job.listing.v1 import BackfillCallback
from nohiki_db_utils import check_and_mark_processed
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from job_correlation_evaluation_service.core.config import get_settings
from job_correlation_evaluation_service.core.kafka import kafka_client
from job_correlation_evaluation_service.db.models import SCHEMA_NAME
from job_correlation_evaluation_service.events.backfill_publisher import (
    BackfillCallerContext,
)
from job_correlation_evaluation_service.repositories import ProfileProjectionRepository
from job_correlation_evaluation_service.services.matcher_service import (
    JobMatcherService,
)
from job_correlation_evaluation_service.services.scoring_service import MLScoringService

logger = get_logger(__name__)

settings = get_settings()
backfill_callback_group_id = f"{settings.kafka_consumer_group}-backfill-callback"

_BACKFILL_BATCH_HANDLER: Final[str] = "handle_backfill_listings:operation-batch:v1"


class _BackfillServiceHolder:
    """Container for module-level service references to avoid global statement."""

    ml_scoring_service: MLScoringService | None = None


_backfill_services = _BackfillServiceHolder()


def _force_rescore_from_callback(message: BackfillCallback) -> bool:
    """Decode optional callback metadata, defaulting safely when absent or malformed."""
    callback = message.callback
    if callback is None or not callback.caller_context:
        return False
    try:
        state = BackfillCallerContext.from_bytes(callback.caller_context)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        AttributeError,
    ):
        return False
    return state.force_rescore if isinstance(state.force_rescore, bool) else False


def _backfill_batch_event_id(message: BackfillCallback, batch_number: int) -> str:
    """Build a stable UUID claim from the immutable callback operation and batch."""
    callback = message.callback
    operation_id = callback.operation_id if callback else ""
    if not operation_id:
        msg = "handle_backfill_listings requires callback.operation_id"
        raise ValueError(msg)
    return str(
        uuid5(
            NAMESPACE_URL,
            f"nohiki:backfill:{operation_id}:{message.pref_id}:{batch_number}",
        )
    )


def set_backfill_ml_scoring_service(service: MLScoringService | None) -> None:
    """Set the ML scoring service for backfill handlers."""
    _backfill_services.ml_scoring_service = service


@kafka_client.message_handler(
    Topics.JOB_CORRELATION_BACKFILL_LISTINGS,
    BackfillCallback,
    group_id=backfill_callback_group_id,
)
@kafka_client.with_db_session()
async def handle_backfill_listings(
    message: BackfillCallback,
    context: MessageContext,
) -> None:
    """Handle backfill callback from job-storage-service.

    Matches each listing in the batch against the specified profile.
    """
    operation_id = message.callback.operation_id if message.callback else "unknown"
    pref_id = message.pref_id
    force_rescore = _force_rescore_from_callback(message)

    if message.error is not None:
        logger.error(
            "Backfill request failed",
            operation_id=operation_id,
            pref_id=pref_id,
            error_code=message.error.error_code,
            error_message=message.error.error_message,
        )
        return

    if message.success is None:
        logger.warning("BackfillCallback missing both success and error", operation_id=operation_id)
        return

    result = message.success
    listings = list(result.listings)
    batch_number = result.batch_number
    total_batches = result.total_batches
    is_final = result.is_final_batch

    logger.info(
        "Processing backfill listings batch",
        operation_id=operation_id,
        pref_id=pref_id,
        batch_number=batch_number,
        total_batches=total_batches,
        listings_count=len(listings),
        is_final_batch=is_final,
        force_rescore=force_rescore,
        correlation_id=context.correlation_id,
    )

    if not listings:
        logger.info(
            "Empty backfill batch received",
            operation_id=operation_id,
            pref_id=pref_id,
            batch_number=batch_number,
        )
        return

    try:
        pref_uuid = UUID(pref_id)
    except ValueError:
        logger.warning(
            "Invalid pref_id format, skipping backfill batch",
            operation_id=operation_id,
            pref_id=pref_id,
        )
        return

    db = context.require_db_session()
    claim_id = _backfill_batch_event_id(message, batch_number)
    if not await check_and_mark_processed(db, SCHEMA_NAME, claim_id, _BACKFILL_BATCH_HANDLER):
        logger.info(
            "Duplicate backfill callback ignored",
            claim_id=claim_id,
            operation_id=operation_id,
            batch_number=batch_number,
        )
        return
    profile_repo = ProfileProjectionRepository(db)
    profile = await profile_repo.get_profile(pref_uuid)

    if profile is None:
        logger.warning(
            "Profile not found for backfill matching",
            operation_id=operation_id,
            pref_id=pref_id,
        )
        return

    matcher_service = JobMatcherService(ml_scoring_service=_backfill_services.ml_scoring_service)
    successful_matches = await matcher_service.match_listings_to_profile(
        db=db,
        listings=listings,
        profile=profile,
        correlation_id=context.correlation_id or "",
        force_rescore=force_rescore,
    )

    logger.info(
        "Backfill batch processing completed",
        operation_id=operation_id,
        pref_id=pref_id,
        batch_number=batch_number,
        total_batches=total_batches,
        successful_matches=successful_matches,
        is_final_batch=is_final,
        correlation_id=context.correlation_id,
    )

"""Kafka handler for profile backfill requests."""

from __future__ import annotations

from dataclasses import dataclass

from nohiki.common.v1 import CommandHeader
from nohiki.job.listing.v1 import BackfillCallback, BackfillRequested, BackfillResult, ListingSnapshot
from nohiki_kafka_client import (
    MessageContext,
    Topics,
    callback_from_command,
    create_event_metadata,
)
from nohiki_observability import get_logger

from job_storage_service.core.config import get_settings
from job_storage_service.core.kafka import kafka_client
from job_storage_service.events.publishers import build_listing_snapshot, load_verified_retrieval_embeddings
from job_storage_service.services.bank_service import JobStoreService

logger = get_logger(__name__)

settings = get_settings()
_backfill_group_id = f"{settings.kafka_consumer_group}-backfill"


@dataclass(frozen=True, slots=True)
class BackfillContext:
    """Context for backfill publishing operations.

    Stores the original CommandHeader directly so publishers can call
    callback_from_command() without reconstructing it from scalar copies.
    """

    command: CommandHeader
    pref_id: str
    user_id: str
    correlation_id: str


@kafka_client.message_handler(
    Topics.JOB_LISTING_BACKFILL_REQUESTED,
    BackfillRequested,
    group_id=_backfill_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_backfill_requested(
    message: BackfillRequested,
    context: MessageContext,
) -> None:
    """Handle backfill request from job-correlation-evaluation-service.

    Queries recent listings and publishes them in batches to the callback topic.
    """
    operation_id = message.command.operation_id
    pref_id = message.pref_id
    user_id = message.user_id

    max_listings = max(1, min(message.max_listings or settings.backfill.default_max_listings, 1000))
    since_days = max(1, min(message.since_days or settings.backfill.default_since_days, 90))
    batch_size = settings.backfill.batch_size

    logger.info(
        "Processing backfill request",
        operation_id=operation_id,
        pref_id=pref_id,
        user_id=user_id,
        max_listings=max_listings,
        since_days=since_days,
        correlation_id=context.correlation_id,
    )

    db = context.require_db_session()
    store_service = JobStoreService()
    listings = await store_service.get_listings_for_backfill(
        db,
        max_listings=max_listings,
        since_days=since_days,
    )

    backfill_ctx = BackfillContext(
        command=message.command,
        pref_id=pref_id,
        user_id=user_id,
        correlation_id=context.correlation_id or operation_id,
    )

    if not listings:
        await _publish_empty_response(backfill_ctx)
        return

    verified_embeddings = await load_verified_retrieval_embeddings(listings)
    snapshots = [
        build_listing_snapshot(
            listing,
            retrieval_embeddings=verified_embeddings.get(str(listing.id)),
        )
        for listing in listings
    ]
    await _publish_batches(snapshots, backfill_ctx, batch_size)


async def _publish_empty_response(ctx: BackfillContext) -> None:
    """Publish empty BackfillCallback when no listings found."""
    event = BackfillCallback(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        callback=callback_from_command(ctx.command),
        pref_id=ctx.pref_id,
        user_id=ctx.user_id,
        success=BackfillResult(
            listings=[],
            batch_number=1,
            total_batches=1,
            is_final_batch=True,
            total_listings=0,
        ),
    )

    await kafka_client.publish(ctx.command.callback_topic, event, key=ctx.pref_id)
    logger.info("Published empty backfill response", operation_id=ctx.command.operation_id, pref_id=ctx.pref_id)


async def _publish_batches(
    snapshots: list[ListingSnapshot],
    ctx: BackfillContext,
    batch_size: int,
) -> None:
    """Publish listing snapshots in batches as BackfillCallback messages."""
    total_listings = len(snapshots)
    total_batches = (total_listings + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, total_listings)
        batch_snapshots = snapshots[start_idx:end_idx]
        is_final = batch_num == total_batches - 1

        event = BackfillCallback(
            metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
            callback=callback_from_command(ctx.command),
            pref_id=ctx.pref_id,
            user_id=ctx.user_id,
            success=BackfillResult(
                listings=batch_snapshots,
                batch_number=batch_num + 1,
                total_batches=total_batches,
                is_final_batch=is_final,
                total_listings=total_listings,
            ),
        )

        await kafka_client.publish(ctx.command.callback_topic, event, key=ctx.pref_id)

        logger.debug(
            "Published backfill batch",
            operation_id=ctx.command.operation_id,
            batch_number=batch_num + 1,
            total_batches=total_batches,
            batch_size=len(batch_snapshots),
        )

    logger.info(
        "Backfill complete",
        operation_id=ctx.command.operation_id,
        pref_id=ctx.pref_id,
        total_listings=total_listings,
        total_batches=total_batches,
    )

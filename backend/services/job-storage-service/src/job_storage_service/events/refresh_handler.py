"""Kafka handler for snapshot refresh requests.

Re-publishes ListingUpdated events from current DB state so ECST consumers
pick up corrected or evolved snapshot data without re-running enrichment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki.common.v1 import ListingStatus, SnapshotRefreshRequested
from nohiki_db_utils import OutboxWriter
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import func, select

from job_storage_service.core.config import get_settings
from job_storage_service.core.kafka import kafka_client
from job_storage_service.db.models import SCHEMA_NAME, Listing
from job_storage_service.events.publishers import (
    OutboxContext,
    load_verified_retrieval_embeddings,
    publish_listing_updated_event,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()

_refresh_group_id = f"{settings.kafka_consumer_group}-refresh"
_BATCH_FLUSH_SIZE = 100


async def _query_refresh_targets(
    db: AsyncSession,
    entity_ids: list[str] | None,
) -> list[Listing]:
    """Query active, enriched listings eligible for snapshot refresh.

    Args:
        db: Database session.
        entity_ids: Specific IDs to refresh, or None for all enriched listings.

    Returns:
        List of Listing models matching the filter criteria.

    """
    stmt = (
        select(Listing)
        .where(Listing.status == ListingStatus.ACTIVE)
        .where(Listing.processed_at.isnot(None))
        .where(Listing.collection_version.isnot(None))
        .where(func.cardinality(Listing.skills_embedding) > 0)
        .where(func.cardinality(Listing.title_embedding) > 0)
    )
    if entity_ids:
        stmt = stmt.where(Listing.id.in_(entity_ids))

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _publish_refreshed_snapshots(
    db: AsyncSession,
    listings: list[Listing],
    correlation_id: str,
) -> int:
    """Build fresh snapshots and write ListingUpdated events to the outbox.

    Flushes periodically to bound transaction size for large refreshes.

    Args:
        db: Database session.
        listings: Listings to re-publish snapshots for.
        correlation_id: Correlation ID for event metadata.

    Returns:
        Number of listings refreshed.

    """
    outbox = OutboxWriter(schema=SCHEMA_NAME)
    verified_embeddings = await load_verified_retrieval_embeddings(listings)

    for idx, job in enumerate(listings, start=1):
        listing_id = str(job.id)
        ctx = OutboxContext(
            db=db,
            outbox=outbox,
            listing_id=listing_id,
            correlation_id=correlation_id,
        )
        await publish_listing_updated_event(
            ctx,
            job,
            retrieval_embeddings=verified_embeddings.get(listing_id),
        )

        if idx % _BATCH_FLUSH_SIZE == 0:
            await db.flush()

    return len(listings)


@kafka_client.message_handler(
    Topics.JOB_LISTING_SNAPSHOT_REFRESH_REQUESTED,
    SnapshotRefreshRequested,
    group_id=_refresh_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_snapshot_refresh_requested(
    message: SnapshotRefreshRequested,
    context: MessageContext,
) -> None:
    """Rebuild and re-publish listing snapshots for ECST consumers.

    Args:
        message: Command with optional entity_ids filter and audit reason.
        context: Kafka message context with DB session.

    """
    correlation_id = context.correlation_id or ""
    entity_ids = list(message.entity_ids) or None

    logger.info(
        "Processing snapshot refresh",
        reason=message.reason,
        entity_count=len(entity_ids) if entity_ids else "all",
        correlation_id=correlation_id,
    )

    db = context.require_db_session()
    listings = await _query_refresh_targets(db, entity_ids)

    if not listings:
        logger.info("No listings found for refresh", correlation_id=correlation_id)
        return

    refreshed = await _publish_refreshed_snapshots(db, listings, correlation_id)
    await db.commit()

    logger.info(
        "Snapshot refresh complete",
        refreshed=refreshed,
        reason=message.reason,
        correlation_id=correlation_id,
    )

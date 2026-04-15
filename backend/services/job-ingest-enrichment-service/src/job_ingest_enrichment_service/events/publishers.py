"""Event publishing functions for enrichment events using outbox pattern."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from nohiki.common.v1 import ErrorInfo, GeoCoordinates, ListingReference, OperationOutcome, ProcessingStatus
from nohiki.job.ingest.v1 import EnrichmentCompleted, StoredListing
from nohiki_db_utils import OutboxEventParams, OutboxWriter
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from job_ingest_enrichment_service.core.config import get_settings
from job_ingest_enrichment_service.db.models import SCHEMA_NAME

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()

AGGREGATE_TYPE: Final[str] = "enrichment"


@dataclass(frozen=True, slots=True)
class EnrichmentPublishContext:
    """Context for publishing EnrichmentCompleted event via outbox."""

    listing_ref: ListingReference
    stored_data: StoredListing
    listing_id: str
    llm_model_id: str
    collection_version: str
    correlation_id: str
    geocoded_coordinates: GeoCoordinates | None = None


async def publish_enrichment_completed_outbox(
    db: AsyncSession,
    ctx: EnrichmentPublishContext,
) -> None:
    """Publish EnrichmentCompleted event via outbox (atomic with DB transaction).

    Use this when there's DB state (e.g., saga) that must be atomic with the event.
    Writes event to outbox table within caller's transaction. Debezium CDC
    captures the outbox entry and publishes to Kafka after commit.

    Args:
        db: Active database session (caller manages transaction).
        ctx: Enrichment publish context with all required event data.

    """
    outbox = OutboxWriter(schema=SCHEMA_NAME)

    event = EnrichmentCompleted(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing=ctx.listing_ref,
        stored_data=ctx.stored_data,
        result=OperationOutcome(status=ProcessingStatus.COMPLETED),
        listing_id=ctx.listing_id,
        llm_model_id=ctx.llm_model_id,
        collection_version=ctx.collection_version,
    )

    if ctx.geocoded_coordinates:
        event.geocoded_coordinates = ctx.geocoded_coordinates

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=ctx.listing_id,
            event_type=Topics.JOB_INGEST_ENRICHMENT_COMPLETED,
            correlation_id=ctx.correlation_id,
        ),
        event=event,
    )

    logger.debug(
        "Wrote enrichment completion event to outbox",
        listing_id=ctx.listing_id,
        correlation_id=ctx.correlation_id,
    )


async def publish_enrichment_failed_outbox(
    db: AsyncSession,
    ctx: EnrichmentPublishContext,
    error: ErrorInfo,
) -> None:
    """Write a terminal failed enrichment outcome atomically with saga state."""
    outbox = OutboxWriter(schema=SCHEMA_NAME)
    event = EnrichmentCompleted(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing=ctx.listing_ref,
        stored_data=StoredListing(),
        result=OperationOutcome(status=ProcessingStatus.FAILED, error=error),
        listing_id=ctx.listing_id,
        llm_model_id=ctx.llm_model_id,
        collection_version=ctx.collection_version,
    )
    if ctx.geocoded_coordinates:
        event.geocoded_coordinates = ctx.geocoded_coordinates
    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=ctx.listing_id,
            event_type=Topics.JOB_INGEST_ENRICHMENT_COMPLETED,
            correlation_id=ctx.correlation_id,
        ),
        event=event,
    )
    logger.debug(
        "Wrote failed enrichment event to outbox",
        listing_id=ctx.listing_id,
        correlation_id=ctx.correlation_id,
        error_code=error.error_code,
    )

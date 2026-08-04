"""Event publishing functions for job storage lifecycle events via outbox pattern."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from nohiki.common.v1 import (
    Compensation,
    CountryCode,
    ListingReference,
    ListingStatus,
    Location,
)
from nohiki.job.listing.v1 import (
    ListingAccepted,
    ListingCreated,
    ListingDeleted,
    ListingSnapshot,
    ListingUpdated,
)
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector
from nohiki_db_utils import OutboxEventParams
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from job_storage_service.core.config import get_settings
from job_storage_service.db.models import Listing

if TYPE_CHECKING:
    from nohiki.job.ingest.v1 import DiscoveredListing
    from nohiki_db_utils import OutboxWriter
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()

AGGREGATE_TYPE = "listing"
MAX_DESCRIPTION_LENGTH = 5000


@dataclass(slots=True)
class OutboxContext:
    """Minimal context for outbox-pattern event publishing."""

    db: AsyncSession
    outbox: OutboxWriter
    listing_id: str
    correlation_id: str | None


@dataclass(slots=True)
class PublishContext(OutboxContext):
    """Extended context that also carries the originating listing reference.

    Functions that build ListingReference-bearing events (accepted, created,
    duplicate) require this. Functions that only need outbox plumbing
    (updated) accept the narrower OutboxContext.
    """

    listing_reference: ListingReference


def _truncate_description(description: str | None) -> str:
    """Truncate description to max length for event size management."""
    if not description:
        return ""
    return description[:MAX_DESCRIPTION_LENGTH] if len(description) > MAX_DESCRIPTION_LENGTH else description


def _build_compensation(job: Listing) -> Compensation | None:
    """Rebuild Compensation proto from the stored JSONB column."""
    if not job.compensation or not isinstance(job.compensation, dict):
        return None

    return Compensation.from_dict(job.compensation)


def _build_location(job: Listing) -> Location | None:
    """Rebuild Location proto from the stored JSONB column.

    Returns None when the country is unspecified, which signals downstream
    consumers that the listing has no usable location data.
    """
    if not job.location or not isinstance(job.location, dict):
        return None

    location = Location.from_dict(job.location)
    if location.country == CountryCode.UNSPECIFIED:
        return None

    return location


def _set_snapshot_timestamps(snapshot: ListingSnapshot, job: Listing) -> None:
    """Set timestamp fields on the snapshot from job data."""
    if job.posted_at:
        snapshot.posted_at = job.posted_at
    snapshot.discovered_at = job.discovered_at
    if job.processed_at:
        snapshot.processed_at = job.processed_at
    if job.created_at:
        snapshot.created_at = job.created_at
    if job.updated_at:
        snapshot.updated_at = job.updated_at


def _build_dense_embedding_vector(
    values: list[float] | None,
    collection_version: str | None,
) -> EmbeddingVector | None:
    """Build an EmbeddingVector with DENSE type from raw float values."""
    if not values or not collection_version:
        return None
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=values),
        collection_version=collection_version,
    )


def build_listing_snapshot(job: Listing) -> ListingSnapshot:
    """Build ListingSnapshot from database model for ECST."""
    snapshot = ListingSnapshot(
        id=str(job.id),
        listing_url=job.listing_url,
        source=job.job_board_source,
        title=job.title or "",
        company_name=job.company_name or "",
        description=_truncate_description(job.description),
        work_arrangement=job.work_arrangement,
        seniority_level=job.seniority_level,
        language=job.language or "",
        version=job.version,
        raw_content_hash=job.raw_content_hash,
        collection_version=job.collection_version or "",
    )

    if job.required_skills:
        snapshot.required_skills.extend(job.required_skills)
    if job.min_experience_years is not None:
        snapshot.experience_years_min = job.min_experience_years
    if job.max_experience_years is not None:
        snapshot.experience_years_max = job.max_experience_years
    if job.company_logo_url:
        snapshot.company_logo_url = job.company_logo_url

    comp = _build_compensation(job)
    if comp:
        snapshot.compensation = comp

    loc = _build_location(job)
    if loc:
        snapshot.location = loc

    skills_emb = _build_dense_embedding_vector(job.skills_embedding, job.collection_version)
    if skills_emb is None:
        msg = f"Listing {job.id} missing required skills_embedding (ECST contract violation)"
        raise ValueError(msg)
    snapshot.skills_embedding = skills_emb

    title_emb = _build_dense_embedding_vector(job.title_embedding, job.collection_version)
    if title_emb is None:
        msg = f"Listing {job.id} missing required title_embedding (ECST contract violation)"
        raise ValueError(msg)
    snapshot.title_embedding = title_emb

    _set_snapshot_timestamps(snapshot, job)
    return snapshot


async def publish_listing_accepted_event(
    ctx: PublishContext,
    discovered_data: DiscoveredListing,
    discovered_at: datetime,
) -> None:
    """Publish listing accepted event via outbox pattern."""
    updated_listing_ref = ListingReference(
        listing_url=ctx.listing_reference.listing_url,
        listing_id=ctx.listing_id,
        external_listing_id=ctx.listing_reference.external_listing_id,
        source=ctx.listing_reference.source,
    )

    event = ListingAccepted(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing=updated_listing_ref,
        discovered_data=discovered_data,
        listing_id=ctx.listing_id,
        discovered_at=discovered_at,
    )

    await ctx.outbox.write_event(
        db=ctx.db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=ctx.listing_id,
            event_type=Topics.JOB_LISTING_ACCEPTED,
            correlation_id=ctx.correlation_id,
        ),
        event=event,
    )
    logger.debug(
        "Published listing accepted event via outbox",
        listing_id=ctx.listing_id,
        correlation_id=ctx.correlation_id,
    )


async def publish_listing_created_event(
    ctx: PublishContext,
    job: Listing,
    *,
    was_updated: bool = False,
    retrieval_embeddings: list[EmbeddingVector],
) -> None:
    """Publish listing created event via outbox pattern."""
    listing_snapshot = build_listing_snapshot(job)
    listing_snapshot.retrieval_embeddings = retrieval_embeddings

    event = ListingCreated(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing=ctx.listing_reference,
        was_updated=was_updated,
        listing_status=ListingStatus.ACTIVE,
        store_metadata={},
        listing_snapshot=listing_snapshot,
    )

    await ctx.outbox.write_event(
        db=ctx.db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=ctx.listing_id,
            event_type=Topics.JOB_LISTING_CREATED,
            correlation_id=ctx.correlation_id,
        ),
        event=event,
    )
    logger.debug(
        "Published listing created event via outbox",
        listing_id=ctx.listing_id,
        correlation_id=ctx.correlation_id,
    )


async def publish_listing_updated_event(
    ctx: OutboxContext,
    job: Listing,
) -> None:
    """Publish listing updated event via outbox pattern."""
    listing_snapshot = build_listing_snapshot(job)

    event = ListingUpdated(
        metadata=create_event_metadata(settings.service_name, ctx.correlation_id),
        listing_id=ctx.listing_id,
        listing_snapshot=listing_snapshot,
    )

    await ctx.outbox.write_event(
        db=ctx.db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=ctx.listing_id,
            event_type=Topics.JOB_LISTING_UPDATED,
            correlation_id=ctx.correlation_id,
        ),
        event=event,
    )
    logger.debug(
        "Published listing updated event via outbox",
        listing_id=ctx.listing_id,
        correlation_id=ctx.correlation_id,
    )


async def publish_listing_deleted_event(
    db: AsyncSession,
    outbox: OutboxWriter,
    listing_id: str,
    correlation_id: str,
) -> None:
    """Publish listing deleted event via outbox pattern."""
    event = ListingDeleted(
        metadata=create_event_metadata(settings.service_name, correlation_id),
        listing_id=listing_id,
    )

    await outbox.write_event(
        db=db,
        params=OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=listing_id,
            event_type=Topics.JOB_LISTING_DELETED,
            correlation_id=correlation_id,
        ),
        event=event,
    )
    logger.debug(
        "Published listing deleted event via outbox",
        listing_id=listing_id,
        correlation_id=correlation_id,
    )

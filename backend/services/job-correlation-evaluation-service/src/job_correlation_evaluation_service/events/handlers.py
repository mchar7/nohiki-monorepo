"""Kafka event handlers for job-correlation-evaluation-service using decorator-based API."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.common.v1 import EventMetadata
from nohiki.job.listing.v1 import ListingCreated, ListingDeleted, ListingUpdated
from nohiki.user.pref.v1 import (
    PrefCreated,
    PrefDeleted,
    PrefUpdated,
    SearchPrefSnapshot,
)
from nohiki_db_utils import check_and_mark_processed
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger

from job_correlation_evaluation_service.core.config import get_settings
from job_correlation_evaluation_service.core.kafka import kafka_client
from job_correlation_evaluation_service.db.models import SCHEMA_NAME
from job_correlation_evaluation_service.events.backfill_publisher import (
    BackfillRequest,
    publish_backfill_request,
)
from job_correlation_evaluation_service.repositories import (
    ProfileProjectionRepository,
)
from job_correlation_evaluation_service.services.matcher_service import (
    JobMatcherService,
)
from job_correlation_evaluation_service.services.scoring_service import MLScoringService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

settings = get_settings()
# All listing CDC handlers (created/updated/deleted) share one group_id so
# that a single consumer instance processes the full lifecycle of a listing
# in order: required to avoid races between create/update for the same
# listing_id, which would otherwise interleave across consumer instances.
primary_group_id = settings.kafka_consumer_group
projection_group_id = f"{settings.kafka_consumer_group}-projection"


class _ServiceHolder:
    """Container for module-level service references to avoid global statement."""

    ml_scoring_service: MLScoringService | None = None


_services = _ServiceHolder()


def set_ml_scoring_service(service: MLScoringService | None) -> None:
    """Set the ML scoring service for event handlers."""
    _services.ml_scoring_service = service
    logger.info(
        "ML scoring service configured for handlers",
        enabled=service is not None,
    )


async def _claim_event(db: AsyncSession, event_id: object, handler_name: str) -> bool:
    """Atomically claim a current-contract Kafka event in its handler transaction."""
    if not isinstance(event_id, str) or not event_id:
        msg = f"{handler_name} requires metadata.event_id"
        raise ValueError(msg)
    return await check_and_mark_processed(db, SCHEMA_NAME, event_id, f"{handler_name}:v1")


def start_event_consumer() -> None:
    """Start the Kafka event consumer."""
    logger.info("Starting event consumer", service=settings.service_name)
    kafka_client.start_consumers()


def _profile_source_revision(snapshot: SearchPrefSnapshot) -> datetime:
    """Return the source-owned revision carried by the ECST snapshot."""
    timestamps = snapshot.timestamps
    revision = timestamps.updated_at if timestamps is not None else None
    if not isinstance(revision, datetime):
        msg = "Profile CDC snapshot requires timestamps.updated_at"
        raise TypeError(msg)
    return revision


def _event_source_revision(metadata: EventMetadata | None) -> datetime:
    """Return the source event revision used when no entity snapshot remains."""
    revision = metadata.timestamp if metadata is not None else None
    if not isinstance(revision, datetime):
        msg = "Profile deletion CDC requires metadata.timestamp"
        raise TypeError(msg)
    return revision


@kafka_client.message_handler(Topics.JOB_LISTING_CREATED, ListingCreated, group_id=primary_group_id)
@kafka_client.with_db_session()
async def handle_job_store_created(message: ListingCreated, context: MessageContext) -> None:
    """Handle job store created events for matching using ECST snapshot."""
    listing_ref = message.listing
    if listing_ref is None:
        logger.error("ListingCreated missing listing reference")
        return

    logger.info(
        "Processing job for matching (ECST)",
        listing_id=listing_ref.listing_id,
        listing_url=listing_ref.listing_url,
        correlation_id=context.correlation_id,
    )

    job = message.listing_snapshot
    if job is None:
        logger.error("ListingCreated missing listing_snapshot")
        return

    metadata = message.metadata
    correlation_id = metadata.correlation_id if metadata and metadata.correlation_id else "unknown"

    db = context.require_db_session()
    matcher_service = JobMatcherService(ml_scoring_service=_services.ml_scoring_service)
    match_count = await matcher_service.match_job_to_profiles(
        db=db,
        job=job,
        correlation_id=correlation_id,
    )

    logger.info(
        "Listing matching completed",
        listing_id=listing_ref.listing_id,
        listing_url=listing_ref.listing_url,
        correlation_id=context.correlation_id,
        scoring_method="ml" if _services.ml_scoring_service else "unavailable",
        matched_profiles=match_count,
    )


@kafka_client.message_handler(Topics.JOB_LISTING_UPDATED, ListingUpdated, group_id=primary_group_id)
@kafka_client.with_db_session()
async def handle_job_store_updated(message: ListingUpdated, context: MessageContext) -> None:
    """Re-score listings whose ECST snapshot was refreshed (typically by enrichment).

    When enrichment completes, job-storage publishes a ListingUpdated CDC
    event carrying the now-enriched ECST snapshot (skills, embeddings,
    metadata). Pre-enrichment correlations carry stale or zero scores; this
    handler re-scores against ALL active profiles (force_rescore=True) and
    upserts the existing rows.
    """
    listing_id = message.listing_id
    if not listing_id:
        logger.error("ListingUpdated missing listing_id")
        return

    job = message.listing_snapshot
    if job is None:
        logger.error("ListingUpdated missing listing_snapshot", listing_id=listing_id)
        return

    logger.info(
        "Re-scoring updated listing against all profiles",
        listing_id=listing_id,
        has_embeddings=bool(job.skills_embedding),
        has_skill_requirements=bool(job.skill_requirements),
        correlation_id=context.correlation_id,
    )

    metadata = message.metadata
    correlation_id = metadata.correlation_id if metadata and metadata.correlation_id else "unknown"

    db = context.require_db_session()
    if not await _claim_event(db, metadata.event_id if metadata else None, "handle_job_store_updated"):
        logger.info(
            "Duplicate listing update ignored",
            event_id=metadata.event_id,
            listing_id=listing_id,
        )
        return
    matcher_service = JobMatcherService(ml_scoring_service=_services.ml_scoring_service)
    await matcher_service.match_job_to_profiles(
        db=db,
        job=job,
        correlation_id=correlation_id,
        force_rescore=True,
    )

    logger.info(
        "Updated listing matching completed",
        listing_id=listing_id,
        correlation_id=context.correlation_id,
    )


@kafka_client.message_handler(Topics.JOB_LISTING_DELETED, ListingDeleted, group_id=primary_group_id)
@kafka_client.with_db_session()
async def handle_job_store_deleted(message: ListingDeleted, context: MessageContext) -> None:
    """Handle job store deleted events for eventual consistency.

    Per EDA best practices, we use event-driven cleanup instead of cross-schema FK CASCADE.
    When a job is deleted from job-storage-service, we dismiss all matches for that job.
    """
    listing_id = message.listing_id

    logger.info(
        "Processing job deletion for correlation cleanup",
        listing_id=listing_id,
        correlation_id=context.correlation_id,
    )

    db = context.require_db_session()
    matcher_service = JobMatcherService()
    dismissed_count = await matcher_service.dismiss_matches_for_deleted_job(
        db=db,
        listing_id=UUID(listing_id),
    )

    logger.info(
        "Listing deletion cleanup completed",
        listing_id=listing_id,
        dismissed_count=dismissed_count,
        correlation_id=context.correlation_id,
    )


@kafka_client.message_handler(Topics.USER_PREF_CREATED, PrefCreated, group_id=projection_group_id)
@kafka_client.with_db_session()
async def handle_profile_created(message: PrefCreated, context: MessageContext) -> None:
    """Handle profile.created.v1 events using ECST pattern.

    1. Stores profile in PostgreSQL projection table
    2. Triggers backfill request to match existing listings against new profile
    """
    pref_id = message.pref_id
    snapshot = message.pref_snapshot

    if snapshot is None:
        logger.error("PrefCreated missing pref_snapshot", pref_id=pref_id)
        return

    logger.info(
        "Storing new profile in projection from ECST snapshot",
        pref_id=pref_id,
        user_id=snapshot.user_id,
        correlation_id=context.correlation_id,
    )

    db = context.require_db_session()
    metadata = message.metadata
    event_id = str(metadata.event_id) if metadata and metadata.event_id else ""
    if not await _claim_event(db, event_id, "handle_profile_created"):
        logger.info("Duplicate profile create ignored", event_id=event_id, pref_id=pref_id)
        return
    repo = ProfileProjectionRepository(db)
    changed = await repo.upsert_profile(snapshot, _profile_source_revision(snapshot))
    if changed:
        logger.info(
            "New profile stored in projection from ECST",
            pref_id=pref_id,
            correlation_id=context.correlation_id,
        )

        if settings.backfill.enabled:
            await publish_backfill_request(
                db,
                BackfillRequest(
                    pref_id=pref_id,
                    user_id=snapshot.user_id,
                    correlation_id=context.correlation_id or "",
                    operation_id=event_id,
                ),
            )
    await db.commit()
    if changed:
        await repo.invalidate_cache()


@kafka_client.message_handler(Topics.USER_PREF_UPDATED, PrefUpdated, group_id=projection_group_id)
@kafka_client.with_db_session()
async def handle_profile_updated(message: PrefUpdated, context: MessageContext) -> None:
    """Handle profile.updated.v1 events using ECST pattern.

    1. Updates profile in PostgreSQL projection table
    2. Triggers backfill to re-score correlations with updated profile embeddings
    """
    pref_id = message.pref_id
    snapshot = message.pref_snapshot

    if snapshot is None:
        logger.error("PrefUpdated missing pref_snapshot", pref_id=pref_id)
        return

    logger.info(
        "Updating profile projection from ECST snapshot",
        pref_id=pref_id,
        user_id=snapshot.user_id,
        correlation_id=context.correlation_id,
    )

    db = context.require_db_session()
    metadata = message.metadata
    event_id = str(metadata.event_id) if metadata and metadata.event_id else ""
    if not await _claim_event(db, event_id, "handle_profile_updated"):
        logger.info("Duplicate profile update ignored", event_id=event_id, pref_id=pref_id)
        return
    repo = ProfileProjectionRepository(db)
    changed = await repo.upsert_profile(snapshot, _profile_source_revision(snapshot))
    if changed:
        logger.info(
            "Profile updated in projection from ECST",
            pref_id=pref_id,
            correlation_id=context.correlation_id,
        )

        if settings.backfill.enabled:
            await publish_backfill_request(
                db,
                BackfillRequest(
                    pref_id=pref_id,
                    user_id=snapshot.user_id,
                    correlation_id=context.correlation_id or "",
                    operation_id=event_id,
                    force_rescore=True,
                ),
            )
    await db.commit()
    if changed:
        await repo.invalidate_cache()


@kafka_client.message_handler(Topics.USER_PREF_DELETED, PrefDeleted, group_id=projection_group_id)
@kafka_client.with_db_session()
async def handle_profile_deleted(message: PrefDeleted, context: MessageContext) -> None:
    """Persist a deletion tombstone ordered with profile snapshot revisions."""
    pref_id = message.pref_id
    user_id = message.user_id
    metadata = message.metadata

    logger.info(
        "Profile deleted, recording projection tombstone",
        pref_id=pref_id,
        user_id=user_id,
        correlation_id=context.correlation_id,
    )

    db = context.require_db_session()
    event_id = str(metadata.event_id) if metadata and metadata.event_id else ""
    if not await _claim_event(db, event_id, "handle_profile_deleted"):
        logger.info("Duplicate profile deletion ignored", event_id=event_id, pref_id=pref_id)
        return
    repo = ProfileProjectionRepository(db)
    changed = await repo.tombstone_profile(
        UUID(pref_id),
        UUID(user_id),
        _event_source_revision(metadata),
    )
    await db.commit()
    if changed:
        await repo.invalidate_cache()

    logger.info(
        "Profile deletion tombstone applied" if changed else "Stale profile deletion ignored",
        pref_id=pref_id,
        correlation_id=context.correlation_id,
    )

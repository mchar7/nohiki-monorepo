"""Job listing domain projection handlers."""

from datetime import UTC, datetime
from uuid import UUID

from nohiki.job.listing.v1 import (
    ListingCreated,
    ListingDeleted,
    ListingSnapshot,
    ListingUpdated,
)
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from bff_service.core.kafka import kafka_client
from bff_service.db.models import JobListingProjection
from bff_service.events.projections._constants import projection_bulk_group_id
from bff_service.events.projections._helpers import (
    extract_enum_name,
    format_location_display,
)

logger = get_logger(__name__)


def _extract_compensation_fields(snapshot: ListingSnapshot) -> dict[str, object]:
    """Extract salary fields from the ListingSnapshot's compensation data.

    Handles both fixed-amount and min/max range compensation. For fixed
    amounts, both salary_min and salary_max are set to the same value.

    Returns:
        Dict with salary_min, salary_max, salary_currency, salary_frequency keys.
    """
    comp = snapshot.compensation
    if not comp:
        return {
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_frequency": None,
        }

    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None

    if comp.fixed_amount and comp.fixed_amount.amount:
        salary_min = comp.fixed_amount.amount.minor_units
        salary_max = comp.fixed_amount.amount.minor_units
        salary_currency = extract_enum_name(comp.fixed_amount.amount.currency)
    else:
        if comp.min_amount and comp.min_amount.amount:
            salary_min = comp.min_amount.amount.minor_units
            salary_currency = extract_enum_name(comp.min_amount.amount.currency)
        if comp.max_amount and comp.max_amount.amount:
            salary_max = comp.max_amount.amount.minor_units
            if salary_currency is None:
                salary_currency = extract_enum_name(comp.max_amount.amount.currency)

    return {
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "salary_frequency": extract_enum_name(comp.frequency),
    }


def _build_listing_values(snapshot: ListingSnapshot, listing_id: UUID, now: datetime) -> dict[str, object]:
    """Build values dict for job listing projection insert."""
    return {
        "id": listing_id,
        "snapshot": snapshot.to_dict(),
        "listing_url": snapshot.listing_url,
        "source": extract_enum_name(snapshot.source) or "UNKNOWN",
        "title": snapshot.title,
        "company_name": snapshot.company_name,
        "description": snapshot.description,
        "location_raw": format_location_display(snapshot.location),
        "work_arrangement": extract_enum_name(snapshot.work_arrangement),
        "seniority_level": extract_enum_name(snapshot.seniority_level),
        "language": snapshot.language or None,
        "required_skills": list(snapshot.required_skills) if snapshot.required_skills else [],
        "version": snapshot.version,
        "raw_content_hash": snapshot.raw_content_hash,
        "posted_at": snapshot.posted_at or None,
        "discovered_at": snapshot.discovered_at or now,
        "created_at": now,
        "country_code": (
            extract_enum_name(snapshot.location.country) if snapshot.location and snapshot.location.country else None
        ),
        "latitude": (
            snapshot.location.coordinates.latitude if snapshot.location and snapshot.location.coordinates else None
        ),
        "longitude": (
            snapshot.location.coordinates.longitude if snapshot.location and snapshot.location.coordinates else None
        ),
        **_extract_compensation_fields(snapshot),
        "company_logo_url": snapshot.company_logo_url or None,
        "experience_years_min": snapshot.experience_years_min,
        "experience_years_max": snapshot.experience_years_max,
    }


def _build_listing_update_set(snapshot: ListingSnapshot) -> dict[str, object]:
    """Build update set dict for job listing projection upsert."""
    return {
        "snapshot": snapshot.to_dict(),
        "title": snapshot.title,
        "company_name": snapshot.company_name,
        "description": snapshot.description,
        "location_raw": format_location_display(snapshot.location),
        "work_arrangement": extract_enum_name(snapshot.work_arrangement),
        "seniority_level": extract_enum_name(snapshot.seniority_level),
        "language": snapshot.language or None,
        "required_skills": list(snapshot.required_skills) if snapshot.required_skills else [],
        "version": snapshot.version,
        "raw_content_hash": snapshot.raw_content_hash,
        "country_code": (
            extract_enum_name(snapshot.location.country) if snapshot.location and snapshot.location.country else None
        ),
        "latitude": (
            snapshot.location.coordinates.latitude if snapshot.location and snapshot.location.coordinates else None
        ),
        "longitude": (
            snapshot.location.coordinates.longitude if snapshot.location and snapshot.location.coordinates else None
        ),
        **_extract_compensation_fields(snapshot),
        "company_logo_url": snapshot.company_logo_url or None,
        "experience_years_min": snapshot.experience_years_min,
        "experience_years_max": snapshot.experience_years_max,
    }


@kafka_client.message_handler(
    Topics.JOB_LISTING_CREATED,
    ListingCreated,
    group_id=projection_bulk_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_listing_created(message: ListingCreated, context: MessageContext) -> None:
    """Handle job listing created event - create projection for frontend display."""
    snapshot = message.listing_snapshot
    if snapshot is None:
        logger.warning("ListingCreated missing listing_snapshot")
        return

    if message.listing is None:
        logger.warning("ListingCreated missing listing reference")
        return

    now = datetime.now(UTC)
    listing_id = UUID(snapshot.id)
    values = _build_listing_values(snapshot, listing_id, now)
    update_set = _build_listing_update_set(snapshot)

    session = context.require_db_session()
    base = insert(JobListingProjection).values(**values)
    # Guard against out-of-order Kafka delivery: only apply the update when the
    # incoming snapshot is at least as new as the row already on disk. Without
    # this predicate a delayed v3 event could overwrite a v5 projection.
    stmt = base.on_conflict_do_update(
        index_elements=["id"],
        set_=update_set,
        where=JobListingProjection.version <= base.excluded.version,
    )
    await session.execute(stmt)
    logger.info("Job listing projection created/updated", listing_id=str(listing_id))


@kafka_client.message_handler(
    Topics.JOB_LISTING_UPDATED,
    ListingUpdated,
    group_id=projection_bulk_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_listing_updated(message: ListingUpdated, context: MessageContext) -> None:
    """Handle job listing updated event - update projection with new snapshot."""
    snapshot = message.listing_snapshot
    if snapshot is None:
        logger.warning("ListingUpdated missing listing_snapshot")
        return

    now = datetime.now(UTC)
    listing_id = UUID(snapshot.id)
    values = _build_listing_values(snapshot, listing_id, now)
    update_set = _build_listing_update_set(snapshot)

    session = context.require_db_session()
    base = insert(JobListingProjection).values(**values)
    stmt = base.on_conflict_do_update(
        index_elements=["id"],
        set_=update_set,
        where=JobListingProjection.version <= base.excluded.version,
    )
    await session.execute(stmt)
    logger.info(
        "Job listing projection updated",
        listing_id=str(listing_id),
        version=snapshot.version,
    )


@kafka_client.message_handler(
    Topics.JOB_LISTING_DELETED,
    ListingDeleted,
    group_id=projection_bulk_group_id,
    preserve_partition_order=False,
)
@kafka_client.with_db_session()
async def handle_listing_deleted(message: ListingDeleted, context: MessageContext) -> None:
    """Handle job listing deleted event - remove from projection."""
    listing_id = UUID(message.listing_id)
    session = context.require_db_session()
    await session.execute(delete(JobListingProjection).where(JobListingProjection.id == listing_id))
    logger.info("Job listing projection deleted", listing_id=str(listing_id))

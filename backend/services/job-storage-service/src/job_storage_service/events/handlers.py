"""Kafka event handlers for job-storage-service."""

from __future__ import annotations

from datetime import UTC, datetime

from nohiki.common.v1 import ProcessingStatus
from nohiki.job.ingest.v1 import EnrichmentCompleted, ListingDiscovered
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import check_and_mark_processed
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from job_storage_service.core.config import get_settings
from job_storage_service.core.kafka import kafka_client
from job_storage_service.db.models import SCHEMA_NAME, ListingIngestSaga
from job_storage_service.services.bank_service import BankOutcome, JobStoreService, RawJobContext, _saga_repo

logger = get_logger(__name__)
settings = get_settings()

# Postgres SQLSTATE codes used to disambiguate IntegrityError causes. CHECK
# violations are validation failures the upstream pre-flight should have
# caught (see _validate_stored_for_banking) and must not be retried; unique
# violations indicate a benign concurrent-insert race resolved by the other
# transaction.
_SQLSTATE_UNIQUE_VIOLATION = "23505"
_SQLSTATE_CHECK_VIOLATION = "23514"


@kafka_client.message_handler(
    Topics.JOB_INGEST_LISTING_DISCOVERED,
    ListingDiscovered,
    group_id=settings.kafka_consumer_group,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_job_raw_found(message: ListingDiscovered, context: MessageContext) -> None:
    """Accept a discovered listing into the in-flight ingest saga."""
    listing = message.listing
    metadata = message.metadata
    discovered_at = message.discovered_at
    discovered_data = message.discovered_data
    correlation_id = metadata.correlation_id

    logger.info(
        "Processing discovered listing",
        listing_url=listing.listing_url,
        query_id=message.query_id,
        correlation_id=correlation_id,
    )

    db = context.require_db_session()
    if isinstance(metadata.event_id, str) and metadata.event_id:
        is_new_event = await check_and_mark_processed(
            db,
            SCHEMA_NAME,
            str(metadata.event_id),
            "handle_job_raw_found",
        )
        if not is_new_event:
            await db.commit()
            logger.info(
                "Duplicate discovered event ignored",
                event_id=str(metadata.event_id),
                listing_url=listing.listing_url,
            )
            return
    store_service = JobStoreService()

    raw_job_ctx = RawJobContext(
        correlation_id=correlation_id or "",
        discovered_at=discovered_at or datetime.now(UTC),
    )

    try:
        result = await store_service.handle_discovered_listing(
            db=db,
            discovered=discovered_data,
            listing_reference=listing,
            context=raw_job_ctx,
            query_id=message.query_id or "",
        )
    except IntegrityError:
        # Partial unique index race: another consumer inserted the same URL
        # between our SELECT and INSERT. The other path emitted ListingAccepted,
        # so we have nothing more to do.
        logger.info(
            "Saga insert race detected; treating as duplicate",
            listing_url=listing.listing_url,
            correlation_id=correlation_id,
        )
        return

    log_message = "Saga accepted (new in-flight ingest)" if result.is_new else "Saga existed (in-flight ingest reused)"
    logger.info(
        log_message,
        saga_id=str(result.saga_id),
        listing_url=listing.listing_url,
        correlation_id=correlation_id,
    )


@kafka_client.message_handler(
    Topics.JOB_INGEST_ENRICHMENT_COMPLETED,
    EnrichmentCompleted,
    group_id=settings.kafka_consumer_group,
)
@kafka_client.with_db_session(auto_commit=False)
async def handle_job_processing_completed(message: EnrichmentCompleted, context: MessageContext) -> None:
    """Promote an enriched listing from the saga ledger to the canonical bank."""
    listing = message.listing
    metadata = message.metadata
    result = message.result
    stored_data = message.stored_data
    collection_version = message.collection_version
    correlation_id = metadata.correlation_id

    # Enrichment passes coordinates separately; attach them to the location
    # so a single JSONB column carries the full Location proto.
    if message.geocoded_coordinates and stored_data.location:
        stored_data.location.coordinates = message.geocoded_coordinates

    if result is not None and result.status == ProcessingStatus.FAILED:
        await _handle_failed_enrichment(
            db=context.require_db_session(),
            listing_url=listing.listing_url,
            error_message=result.error.error_message if result.error else None,
            correlation_id=correlation_id,
        )
        return

    logger.info(
        "Banking stored listing",
        listing_url=listing.listing_url,
        correlation_id=correlation_id,
    )

    db = context.require_db_session()
    store_service = JobStoreService()

    try:
        outcome = await store_service.bank_stored_listing(
            db=db,
            stored=stored_data,
            listing_reference=listing,
            correlation_id=correlation_id or "",
            collection_version=collection_version,
        )
    except IntegrityError as exc:
        is_concurrent_duplicate = _log_integrity_violation(
            exc,
            listing_url=listing.listing_url,
            correlation_id=correlation_id,
        )
        if is_concurrent_duplicate:
            return
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if sqlstate == _SQLSTATE_CHECK_VIOLATION:
            await db.rollback()
            await db.execute(
                update(ListingIngestSaga)
                .where(
                    ListingIngestSaga.listing_url == listing.listing_url,
                    ListingIngestSaga.status == "PENDING",
                )
                .values(status="FAILED", version=ListingIngestSaga.version + 1)
            )
            await db.commit()
            return
        raise

    _log_bank_outcome(outcome, listing_url=listing.listing_url, correlation_id=correlation_id)


async def _handle_failed_enrichment(
    *,
    db: object,
    listing_url: str,
    error_message: str | None,
    correlation_id: str | None,
) -> None:
    """Mark the in-flight saga FAILED so retries do not loop forever.

    Without this the saga sits in PENDING until the stale-saga sweep eventually
    expires it; explicit failure attributes the outcome to enrichment and gives
    operators a clear audit trail.
    """
    logger.warning(
        "Skipping failed enrichment",
        listing_url=listing_url,
        error_message=error_message,
        correlation_id=correlation_id,
    )

    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    if not isinstance(db, AsyncSession):
        db_type = type(db).__name__
        msg = f"Expected AsyncSession, got {db_type}"
        raise TypeError(msg)

    saga_row = await db.execute(
        select(ListingIngestSaga.id).where(
            ListingIngestSaga.listing_url == listing_url,
            ListingIngestSaga.status == "PENDING",
        )
    )
    saga_id = saga_row.scalar_one_or_none()
    if saga_id is None:
        return

    try:
        await _saga_repo.fail(db, saga_id, reason=error_message or "enrichment_failed")
        await db.commit()
    except Exception:
        # A stale-saga sweep racing with us may have already transitioned the
        # row; that is acceptable, log and continue.
        logger.exception(
            "Failed to mark saga as FAILED",
            listing_url=listing_url,
            saga_id=str(saga_id),
            correlation_id=correlation_id,
        )


def _log_integrity_violation(
    exc: IntegrityError,
    *,
    listing_url: str,
    correlation_id: str | None,
) -> bool:
    """Log an integrity violation and return whether it is a benign unique race."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    match sqlstate:
        case s if s == _SQLSTATE_CHECK_VIOLATION:
            logger.error(
                "CHECK constraint violation reached the database (pre-flight validation gap)",
                listing_url=listing_url,
                correlation_id=correlation_id,
                sqlstate=sqlstate,
            )
            return False
        case s if s == _SQLSTATE_UNIQUE_VIOLATION:
            logger.info(
                "Enriched listing race resolved upstream",
                listing_url=listing_url,
                correlation_id=correlation_id,
            )
            return True
        case _:
            logger.warning(
                "IntegrityError during banking",
                listing_url=listing_url,
                correlation_id=correlation_id,
                sqlstate=sqlstate,
            )
            return False


def _log_bank_outcome(
    outcome: BankOutcome,
    *,
    listing_url: str,
    correlation_id: str | None,
) -> None:
    """Translate the BankOutcome status into a single structured log line."""
    match outcome.status:
        case "banked":
            action = "updated" if outcome.was_updated else "created"
            logger.info(
                "Stored listing banked",
                action=action,
                listing_id=outcome.listing_id,
                listing_url=listing_url,
                correlation_id=correlation_id,
            )
        case "replay":
            logger.info(
                "Stored listing replay (idempotent)",
                listing_url=listing_url,
                correlation_id=correlation_id,
            )
        case "orphan":
            # Orphan = enrichment for a URL no saga ever accepted. Surface as
            # a typed validation error so the message DLQs cleanly without
            # retry storms; the bank service has already incremented the
            # orphan counter for ops visibility.
            raise ValidationError(
                field_name="saga",
                invalid_value=listing_url,
                constraint="missing PENDING saga for enrichment completion",
            )

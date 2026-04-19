"""Core job store service for managing canonical job storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from nohiki.common.v1 import ListingReference, ListingStatus
from nohiki.job.ingest.v1 import DiscoveredListing, StoredListing
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import OutboxWriter, SagaRepository, build_prefix_tsquery
from nohiki_db_utils.saga.models import SagaStatus
from nohiki_observability import get_logger
from nohiki_qdrant_client import UpsertPayload, VectorPoint
from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from uuid_utils.compat import uuid7

from job_storage_service.core.config import get_jobs_collection_name, get_qdrant_client
from job_storage_service.core.constants import SAGA_TTL
from job_storage_service.db.models import SCHEMA_NAME, ListingIngestSaga, ListingVersion
from job_storage_service.db.models import Listing as JobTable
from job_storage_service.events.publishers import (
    PublishContext,
    build_listing_snapshot,
    publish_listing_accepted_event,
    publish_listing_created_event,
    publish_listing_deleted_event,
    publish_listing_updated_event,
)
from job_storage_service.metrics.ingest import get_ingest_metrics
from job_storage_service.services.data_mapper import JobDataMapper, compute_dedup_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# listings.description CHECK constraint requires length >= 200; pre-validate
# so a violation surfaces as a typed ValidationError rather than a generic
# IntegrityError the handler cannot distinguish from a unique-violation race.
_MIN_DESCRIPTION_LENGTH = 200
_MAX_TITLE_LENGTH = 500
_MAX_COMPANY_NAME_LENGTH = 500
_MAX_COMPANY_LOGO_URL_LENGTH = 2048
_MAX_LANGUAGE_LENGTH = 5
_MAX_COLLECTION_VERSION_LENGTH = 10


_saga_repo: SagaRepository[ListingIngestSaga] = SagaRepository(ListingIngestSaga)


@dataclass(slots=True)
class RawJobContext:
    """Context information for processing raw jobs."""

    correlation_id: str
    discovered_at: datetime


@dataclass(slots=True)
class _SagaIngestResult:
    """Outcome of handle_discovered_listing.

    Attributes:
        saga_id: UUID of the saga row anchoring the in-flight ingest.
        is_new: True when a fresh saga row was inserted; False when an
            existing PENDING saga was reused (rescrape variant or idempotent
            redelivery).
    """

    saga_id: UUID
    is_new: bool


@dataclass(slots=True)
class BankOutcome:
    """Result of bank_stored_listing.

    ``status`` distinguishes:
      - ``"banked"``: a canonical listings row was inserted/updated.
      - ``"replay"``: saga is already COMPLETED: idempotent Kafka redelivery, no-op.
      - ``"orphan"``: no saga row at all: enrichment for a URL we never accepted.
    """

    status: str
    listing_id: str | None = None
    was_updated: bool = False


def _job_vector_point(job: JobTable, stored: StoredListing) -> VectorPoint:
    """Map the enriched listing to its single manifest-schema Qdrant point."""
    return VectorPoint(
        point_id=str(job.id),
        embeddings=list(stored.retrieval_embeddings),
        payload=UpsertPayload(
            entity_id=str(job.id),
            entity_type="job",
            collection_version=job.collection_version or "",
            content_hash=stored.content_hash,
            is_active=job.status == ListingStatus.ACTIVE,
            extra={
                "title": job.title,
                "company_name": job.company_name,
                "description": job.description,
            },
        ),
    )


class JobStoreService:
    """Service for managing job store operations."""

    def __init__(self) -> None:
        """Initialize JobStoreService."""

    async def get_job_by_id(self, db: AsyncSession, listing_id: str) -> JobTable | None:
        """Get job by ID."""
        stmt = select(JobTable).where(JobTable.id == listing_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_jobs_by_ids(self, db: AsyncSession, listing_ids: list[str]) -> list[JobTable]:
        """Get multiple jobs by IDs."""
        stmt = select(JobTable).where(JobTable.id.in_(listing_ids))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def search_jobs_fts(
        self,
        db: AsyncSession,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobTable]:
        """Search jobs using full-text search with prefix matching."""
        prefix_query = build_prefix_tsquery(query)
        if not prefix_query:
            return []

        ts_query = func.to_tsquery("english", prefix_query)
        stmt = (
            select(JobTable)
            .where(JobTable.status == ListingStatus.ACTIVE)
            .where(JobTable.search_vector.op("@@")(ts_query))
            .order_by(func.ts_rank_cd(JobTable.search_vector, ts_query).desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        jobs = list(result.scalars().all())

        logger.debug(
            "FTS search completed",
            query=query,
            results_count=len(jobs),
        )

        return jobs

    async def search_jobs_by_skills(
        self,
        db: AsyncSession,
        skills: list[str],
        *,
        match_all: bool = False,
        limit: int = 50,
    ) -> list[JobTable]:
        """Search jobs by required skills (active listings only)."""
        base_query = select(JobTable).where(JobTable.status == ListingStatus.ACTIVE).limit(limit)
        if match_all:
            result = await db.execute(base_query.where(JobTable.required_skills.contains(skills)))
        else:
            result = await db.execute(base_query.where(JobTable.required_skills.overlap(skills)))

        jobs = list(result.scalars().all())

        logger.debug(
            "Skills search completed",
            skills=skills,
            match_all=match_all,
            results_count=len(jobs),
        )

        return jobs

    async def get_jobs_by_location(
        self,
        db: AsyncSession,
        *,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        limit: int = 50,
    ) -> list[JobTable]:
        """Search jobs by location (active listings only)."""
        conditions = [JobTable.status == ListingStatus.ACTIVE]

        if city:
            conditions.append(JobTable.location["city"].astext.ilike(f"%{city}%"))
        if state:
            conditions.append(JobTable.location["state"].astext.ilike(f"%{state}%"))
        if country:
            conditions.append(JobTable.location["country"].astext.ilike(f"%{country}%"))

        if len(conditions) == 1:
            return []

        result = await db.execute(select(JobTable).where(*conditions).limit(limit))

        return list(result.scalars().all())

    async def get_recent_jobs(
        self,
        db: AsyncSession,
        *,
        hours: int = 24,
        limit: int = 100,
    ) -> list[JobTable]:
        """Get recently scraped active jobs."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        result = await db.execute(
            select(JobTable)
            .where(JobTable.status == ListingStatus.ACTIVE)
            .where(JobTable.discovered_at >= cutoff)
            .order_by(JobTable.discovered_at.desc())
            .limit(limit)
        )

        return list(result.scalars().all())

    async def get_listings_for_backfill(
        self,
        db: AsyncSession,
        *,
        max_listings: int = 500,
        since_days: int = 30,
    ) -> list[JobTable]:
        """Get recent listings for profile backfill.

        Queries active, enriched listings from the last N days, ordered by recency.
        Used when a new profile is created to match against existing jobs.

        Args:
            db: Database session.
            max_listings: Maximum number of listings to return.
            since_days: Only include listings scraped within this many days.

        Returns:
            List of Listing database models.

        """
        cutoff = datetime.now(UTC) - timedelta(days=since_days)

        result = await db.execute(
            select(JobTable)
            .where(JobTable.status == ListingStatus.ACTIVE)
            .where(JobTable.discovered_at >= cutoff)
            .where(JobTable.processed_at.isnot(None))
            .where(JobTable.collection_version.isnot(None))
            .where(func.cardinality(JobTable.skills_embedding) > 0)
            .where(func.cardinality(JobTable.title_embedding) > 0)
            .order_by(JobTable.discovered_at.desc())
            .limit(max_listings)
        )

        listings = list(result.scalars().all())

        logger.info(
            "Retrieved listings for backfill",
            count=len(listings),
            max_listings=max_listings,
            since_days=since_days,
        )

        return listings

    async def _get_job_by_dedup_hash(self, db: AsyncSession, dedup_hash: str) -> JobTable | None:
        """Get job by dedup hash (cross-source deduplication)."""
        stmt = select(JobTable).where(JobTable.dedup_hash == dedup_hash)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_job_by_url(self, db: AsyncSession, listing_url: str) -> JobTable | None:
        """Locate a previously banked listings row by URL.

        Used as a fallback when dedup_hash misses but a row may already exist
        for the same URL (e.g., cross-source variants whose posted_at differs).
        """
        stmt = select(JobTable).where(JobTable.listing_url == listing_url)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_pending_saga_by_url_for_update(
        self,
        db: AsyncSession,
        listing_url: str,
    ) -> ListingIngestSaga | None:
        """Find and lock the in-flight PENDING saga for a listing URL, if any.

        Two concurrent ``EnrichmentCompleted`` deliveries for the same URL would
        otherwise both read the PENDING saga, both bank a listings row, and both
        publish ListingCreated. The row lock serializes them so the second
        transaction blocks until the first commits, and then sees the saga in
        COMPLETED state and skips.
        """
        stmt = (
            select(ListingIngestSaga)
            .where(
                ListingIngestSaga.listing_url == listing_url,
                ListingIngestSaga.status == SagaStatus.PENDING,
            )
            .with_for_update()
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_any_saga_by_url(self, db: AsyncSession, listing_url: str) -> ListingIngestSaga | None:
        """Return the most recent saga (any status) for a URL, for diagnostic logging."""
        stmt = (
            select(ListingIngestSaga)
            .where(ListingIngestSaga.listing_url == listing_url)
            .order_by(ListingIngestSaga.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def _store_version_history(
        self,
        db: AsyncSession,
        job: JobTable,
        correlation_id: str,
        change_type: str,
    ) -> None:
        """Store the current job state as a version in history before updating."""
        listing_snapshot = build_listing_snapshot(job)
        snapshot_dict = listing_snapshot.to_dict()

        version_record = ListingVersion(
            listing_id=job.id,
            version=job.version,
            raw_content_hash=job.raw_content_hash,
            snapshot=snapshot_dict,
            change_type=change_type,
            correlation_id=correlation_id,
        )

        db.add(version_record)

        logger.debug(
            "Stored version history",
            listing_id=str(job.id),
            version=job.version,
            change_type=change_type,
        )

    async def delete_job(self, db: AsyncSession, listing_id: str) -> None:
        """Delete a listing vector before publishing its canonical deletion."""
        logger.info("Deleting job", listing_id=listing_id)

        correlation_id = str(uuid7())
        await get_qdrant_client().delete_points(get_jobs_collection_name(), [listing_id])

        stmt = delete(JobTable).where(JobTable.id == listing_id)
        await db.execute(stmt)

        outbox = OutboxWriter(schema=SCHEMA_NAME)
        await publish_listing_deleted_event(db, outbox, listing_id, correlation_id)

        await db.commit()

        logger.info("Listing deleted", listing_id=listing_id)

    async def handle_discovered_listing(
        self,
        db: AsyncSession,
        discovered: DiscoveredListing,
        listing_reference: ListingReference,
        context: RawJobContext,
        *,
        query_id: str = "",
    ) -> _SagaIngestResult:
        """Accept a discovered listing into the in-flight saga ledger.

        The canonical listings table receives nothing here: it is reserved for
        post-enrichment rows that satisfy the NOT NULL/structured constraints.
        Instead, we insert (or update in place) a ListingIngestSaga row keyed
        by listing_url for in-flight uniqueness, and publish ListingAccepted so
        downstream enrichment can proceed using saga.id as the listing_id.

        Returns:
            _SagaIngestResult describing the outcome.

        """
        content_hash = discovered.content_hash
        listing_url = listing_reference.listing_url
        source = listing_reference.source or discovered.source

        logger.info(
            "Accepting discovered listing into saga",
            listing_url=listing_url,
            content_hash=content_hash[:16],
            correlation_id=context.correlation_id,
        )

        existing_saga = await self._get_pending_saga_by_url_for_update(db, listing_url)
        outbox = OutboxWriter(schema=SCHEMA_NAME)
        is_idempotent_redelivery = False
        match existing_saga:
            case None:
                saga = ListingIngestSaga(
                    listing_url=listing_url,
                    external_listing_id=listing_reference.external_listing_id or discovered.external_id or None,
                    job_board_source=source,
                    query_id=query_id,
                    correlation_id=context.correlation_id,
                    content_hash=content_hash,
                    discovered_data=discovered.to_dict(),
                    discovered_at=context.discovered_at,
                    expected_callbacks=1,
                    expires_at=datetime.now(UTC) + SAGA_TTL,
                )
                saga = await _saga_repo.create(db, saga)
                is_new = True
            case _ if existing_saga.content_hash == content_hash:
                # Same content_hash on a PENDING saga -> Kafka redelivery; no state
                # change required and no second ListingAccepted is emitted (downstream
                # consumers are responsible for their own idempotency on saga.id).
                saga = existing_saga
                is_new = False
                is_idempotent_redelivery = True
            case _:
                # Same URL, different content_hash: rescrape variant landed before
                # enrichment completed. Refresh the payload but preserve the
                # original correlation_id so the upstream discovery chain stays
                # traceable; the new correlation is captured in the log line.
                logger.info(
                    "Rescrape variant arrived before enrichment; refreshing saga payload",
                    saga_id=str(existing_saga.id),
                    listing_url=listing_url,
                    original_correlation_id=existing_saga.correlation_id,
                    new_correlation_id=context.correlation_id,
                )
                existing_saga.content_hash = content_hash
                existing_saga.discovered_data = discovered.to_dict()
                existing_saga.discovered_at = context.discovered_at
                saga = existing_saga
                is_new = False

        saga_id = saga.id
        listing_id_str = str(saga_id)

        if is_idempotent_redelivery:
            await db.commit()
            logger.info(
                "Discovered listing already accepted; idempotent no-op",
                saga_id=listing_id_str,
                listing_url=listing_url,
                correlation_id=context.correlation_id,
            )
            return _SagaIngestResult(saga_id=saga_id, is_new=False)

        pub_ctx = PublishContext(
            db=db,
            outbox=outbox,
            listing_id=listing_id_str,
            listing_reference=ListingReference(
                listing_url=listing_url,
                listing_id=listing_id_str,
                external_listing_id=listing_reference.external_listing_id,
                source=source,
            ),
            correlation_id=context.correlation_id,
        )

        await publish_listing_accepted_event(pub_ctx, discovered, context.discovered_at)
        await db.commit()

        logger.info(
            "Discovered listing saga recorded",
            saga_id=listing_id_str,
            listing_url=listing_url,
            is_new=is_new,
            correlation_id=context.correlation_id,
        )

        return _SagaIngestResult(saga_id=saga_id, is_new=is_new)

    async def bank_stored_listing(
        self,
        db: AsyncSession,
        stored: StoredListing,
        listing_reference: ListingReference,
        correlation_id: str,
        collection_version: str,
    ) -> BankOutcome:
        """Promote an in-flight saga to the canonical listings table on enrichment.

        Lookup order:
        1. PENDING saga by listing_url (locked with FOR UPDATE so concurrent
           ``EnrichmentCompleted`` deliveries for the same URL serialize).
        2. Existing listings row by dedup_hash (cross-source dedup hit). If
           present, UPDATE that row; aggregate_id stays anchored to the
           pre-existing canonical row.
        3. Existing listings row by listing_url. URL fallback covers the case
           where the same URL was banked previously with a different posted_at
           (different dedup_hash).
        4. Otherwise INSERT a new listings row with id = saga.id so the saga's
           UUID becomes the canonical listing_id.

        Saga completion uses optimistic locking by bumping ``version`` and
        running an UPDATE keyed on the prior version. Failure indicates a
        concurrent transition (e.g., EXPIRED race) and is surfaced.

        Returns:
            BankOutcome describing what happened. ``status`` is one of
            "banked", "replay", or "orphan".

        Raises:
            ValidationError: When ``stored`` data fails listings table
                constraints (description length, location structure).

        """
        listing_url = listing_reference.listing_url

        logger.info("Banking stored listing", listing_url=listing_url, correlation_id=correlation_id)

        saga = await self._get_pending_saga_by_url_for_update(db, listing_url)
        if saga is None:
            return await self._classify_missing_saga(db, listing_url, correlation_id)

        if stored.content_hash != saga.content_hash:
            logger.warning(
                "Stale enrichment arrival; content_hash mismatch",
                listing_url=listing_url,
                saga_id=str(saga.id),
                saga_content_hash=saga.content_hash[:16],
                stored_content_hash=stored.content_hash[:16],
                correlation_id=correlation_id,
            )
            return BankOutcome(status="replay")

        self._validate_stored_for_banking(stored)
        if not collection_version or len(collection_version) > _MAX_COLLECTION_VERSION_LENGTH:
            raise ValidationError(
                field_name="collection_version",
                invalid_value=collection_version,
                constraint=f"non-empty version with length <= {_MAX_COLLECTION_VERSION_LENGTH} is required",
            )

        mapper = JobDataMapper()
        job_data = mapper.from_stored(stored, correlation_id, collection_version)
        job_data["listing_url"] = listing_url
        job_data["job_board_source"] = listing_reference.source or stored.source
        job_data["status"] = ListingStatus.ACTIVE

        dedup_hash = job_data["dedup_hash"]
        if not isinstance(dedup_hash, str):
            msg = f"dedup_hash must be str, got {type(dedup_hash).__name__}"
            raise TypeError(msg)
        existing = await self._get_job_by_dedup_hash(db, dedup_hash) or await self._get_job_by_url(db, listing_url)

        outbox = OutboxWriter(schema=SCHEMA_NAME)

        if existing is not None:
            listing_id_str, was_updated = await self._update_existing_listing(
                db,
                existing=existing,
                job_data=job_data,
                correlation_id=correlation_id,
            )
        else:
            listing_id_str = await self._insert_new_listing(db, saga_id=saga.id, job_data=job_data)
            was_updated = False

        job = await self.get_job_by_id(db, listing_id_str)
        if job is None:
            msg = f"Listing {listing_id_str} not found after banking"
            raise RuntimeError(msg)

        # Qdrant is deliberately written before canonical CDC enters the outbox.
        # A failure aborts this database transaction; replay replaces this UUID point.
        await get_qdrant_client().upsert_vector_points_batch(
            get_jobs_collection_name(),
            [_job_vector_point(job, stored)],
        )
        pub_ctx = PublishContext(
            db=db,
            outbox=outbox,
            listing_id=listing_id_str,
            listing_reference=listing_reference,
            correlation_id=correlation_id,
        )

        await publish_listing_created_event(
            pub_ctx,
            job,
            was_updated=was_updated,
            retrieval_embeddings=list(stored.retrieval_embeddings),
        )
        if was_updated:
            await publish_listing_updated_event(pub_ctx, job)

        await self._complete_saga_atomically(db, saga)
        await db.commit()

        logger.info(
            "Stored listing banked",
            listing_id=listing_id_str,
            was_updated=was_updated,
            version=job.version,
            saga_id=str(saga.id),
            correlation_id=correlation_id,
        )

        return BankOutcome(status="banked", listing_id=listing_id_str, was_updated=was_updated)

    async def _classify_missing_saga(
        self,
        db: AsyncSession,
        listing_url: str,
        correlation_id: str,
    ) -> BankOutcome:
        """Distinguish idempotent replay (saga COMPLETED) from orphan (no saga/expired/failed).

        Orphans signal a contract break: enrichment for a URL we never accepted or
        enrichment arriving after the saga timed out or failed. These bump the orphan
        counter so they show up in dashboards rather than being silently dropped.
        """
        any_saga = await self._get_any_saga_by_url(db, listing_url)
        if any_saga is not None:
            if any_saga.status == "COMPLETED":
                logger.info(
                    "Saga already finalised; idempotent replay",
                    listing_url=listing_url,
                    saga_id=str(any_saga.id),
                    saga_status=str(any_saga.status),
                    correlation_id=correlation_id,
                )
                return BankOutcome(status="replay")
            if any_saga.status in ("EXPIRED", "FAILED"):
                # Late delivery for a saga that timed out or failed; operationally
                # significant data loss
                get_ingest_metrics().record_orphan_completion()
                logger.warning(
                    "Late enrichment delivery; saga already expired or failed",
                    listing_url=listing_url,
                    saga_id=str(any_saga.id),
                    saga_status=str(any_saga.status),
                    correlation_id=correlation_id,
                )
                return BankOutcome(status="orphan")

        get_ingest_metrics().record_orphan_completion()
        logger.warning(
            "Enrichment completion has no matching saga (orphan)",
            listing_url=listing_url,
            correlation_id=correlation_id,
        )
        return BankOutcome(status="orphan")

    @staticmethod
    def _validate_stored_for_banking(stored: StoredListing) -> None:
        """Pre-flight checks for listings table constraints.

        Surfaces validation failures as a typed ``ValidationError`` (DLQ) before
        we attempt the INSERT, so we do not conflate constraint violations with
        the unique-violation race-resolution path in the handler layer.
        """
        if not stored.description or len(stored.description) < _MIN_DESCRIPTION_LENGTH:
            raise ValidationError(
                field_name="stored.description",
                invalid_value=f"len={len(stored.description) if stored.description else 0}",
                constraint=f"length(description) >= {_MIN_DESCRIPTION_LENGTH} (chk_description_length)",
            )
        bounded_fields = (
            ("stored.title", stored.title, _MAX_TITLE_LENGTH),
            ("stored.company_name", stored.company_name, _MAX_COMPANY_NAME_LENGTH),
            ("stored.company_logo_url", stored.company_logo_url, _MAX_COMPANY_LOGO_URL_LENGTH),
            ("stored.language", stored.language, _MAX_LANGUAGE_LENGTH),
        )
        for field_name, value, max_length in bounded_fields:
            if value and len(value) > max_length:
                raise ValidationError(
                    field_name=field_name,
                    invalid_value=f"len={len(value)}",
                    constraint=f"length <= {max_length}",
                )
        if not stored.skills_embedding or not stored.skills_embedding.dense or not stored.skills_embedding.dense.values:
            raise ValidationError(
                field_name="stored.skills_embedding",
                invalid_value=None,
                constraint="non-empty dense embedding is required",
            )
        if not stored.title_embedding or not stored.title_embedding.dense or not stored.title_embedding.dense.values:
            raise ValidationError(
                field_name="stored.title_embedding",
                invalid_value=None,
                constraint="non-empty dense embedding is required",
            )
        if not stored.location:
            raise ValidationError(
                field_name="stored.location",
                invalid_value=None,
                constraint="location is required (chk_location_json)",
            )

    async def _complete_saga_atomically(self, db: AsyncSession, saga: ListingIngestSaga) -> None:
        """Transition saga PENDING -> COMPLETED with optimistic locking.

        SagaRepository.complete cannot be reused here because the bank flow
        already wrote upstream outbox events (ListingCreated and possibly
        ListingUpdated) and the repository signature accepts only a single
        outbox event. We instead run a direct UPDATE keyed on the prior
        version so a concurrent EXPIRED transition cannot silently overwrite
        us.

        Mutating the in-memory ORM instance before the UPDATE would trigger
        SQLAlchemy autoflush and bump the version to ``prior_version + 1``,
        which would then make our explicit UPDATE WHERE version = prior_version
        match zero rows. We therefore expire the in-memory copy and run the
        UPDATE as raw SQL against the row.
        """
        prior_version = saga.version
        expected_callbacks = saga.expected_callbacks
        saga_id = saga.id

        # Drop the ORM attribute state so autoflush does not race with the
        # explicit UPDATE statement below.
        db.expunge(saga)

        result = await db.execute(
            update(ListingIngestSaga)
            .where(ListingIngestSaga.id == saga_id, ListingIngestSaga.version == prior_version)
            .values(
                status=SagaStatus.COMPLETED,
                received_callbacks=expected_callbacks,
                version=prior_version + 1,
            )
        )
        # SQLAlchemy returns CursorResult for UPDATE but the public Result
        # type widens; cast keeps ty strict-mode happy without changing
        # runtime semantics.
        if cast(CursorResult[Any], result).rowcount == 0:
            msg = (
                f"Saga {saga_id} version conflict: expected version {prior_version} "
                "but row was modified concurrently (likely EXPIRED by stale-saga sweep)"
            )
            raise RuntimeError(msg)

    async def _update_existing_listing(
        self,
        db: AsyncSession,
        *,
        existing: JobTable,
        job_data: dict[str, object],
        correlation_id: str,
    ) -> tuple[str, bool]:
        """Apply enrichment data onto an existing canonical listing row."""
        if existing.skills_embedding and existing.title_embedding:
            self._store_version_history(db, existing, correlation_id, "enriched")
        job_data["version"] = existing.version + 1
        job_data["discovered_at"] = existing.discovered_at

        update_stmt = update(JobTable).where(JobTable.id == existing.id).values(**job_data).returning(JobTable.id)
        result = await db.execute(update_stmt)
        row = result.fetchone()
        if row is None:
            msg = "UPDATE operation returned no results"
            raise RuntimeError(msg)
        return str(row.id), True

    async def _insert_new_listing(
        self,
        db: AsyncSession,
        *,
        saga_id: UUID,
        job_data: dict[str, object],
    ) -> str:
        """Insert a fresh canonical listing row whose id matches the saga UUID."""
        job_data["id"] = saga_id
        job_data["version"] = 1
        insert_stmt = insert(JobTable).values(**job_data).returning(JobTable.id)
        result = await db.execute(insert_stmt)
        row = result.fetchone()
        if row is None:
            msg = "INSERT operation returned no results"
            raise RuntimeError(msg)
        return str(row.id)


__all__ = [
    "BankOutcome",
    "JobStoreService",
    "RawJobContext",
    "compute_dedup_hash",
]

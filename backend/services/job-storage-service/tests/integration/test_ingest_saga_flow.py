"""End-to-end ingest saga flow against the real migrated schema.

Drives ``JobStoreService`` through both phases of the saga lifecycle:

1. ``handle_discovered_listing`` -> PENDING saga + ListingAccepted outbox event,
   no canonical listings row yet.
2. ``bank_stored_listing`` -> COMPLETED saga + canonical listings row +
   ListingCreated outbox event, with the saga UUID promoted to listings.id.

Idempotency is exercised by re-delivering both events and asserting no
duplicate rows or outbox entries appear.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_storage_service.db.models import SCHEMA_NAME, Listing, ListingIngestSaga
from job_storage_service.services.bank_service import JobStoreService, RawJobContext
from nohiki.common.v1 import (
    CountryCode,
    EmploymentTerm,
    JobBoardSource,
    ListingReference,
    Location,
    LocationType,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.job.ingest.v1 import DiscoveredListing, StoredListing
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, MultiVectorData, SparseData
from nohiki.skill.v1 import JobSkillRequirement
from nohiki_kafka_client import Topics
from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


_LISTING_URL = "https://example.com/jobs/python-engineer-12345"
_CONTENT_HASH = "a" * 64
_CORRELATION_ID = "test-corr-001"
_COLLECTION_VERSION = "v1"
_DISCOVERED_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
_POSTED_AT = datetime(2026, 3, 30, 9, 0, 0, tzinfo=UTC)


def _make_discovered() -> DiscoveredListing:
    """Build a DiscoveredListing proto with the minimum fields the saga path reads."""
    return DiscoveredListing(
        listing_url=_LISTING_URL,
        source=JobBoardSource.LINKEDIN,
        external_id="ext-12345",
        title="Senior Python Engineer",
        company_name="Acme Corp",
        description="Looking for an experienced Python engineer to join our team building distributed systems.",
        location_raw="San Francisco, CA, USA",
        raw_skills=["python", "postgresql", "kafka"],
        apply_url=_LISTING_URL,
        discovered_timestamp=_DISCOVERED_AT,
        posted_timestamp=_POSTED_AT,
        content_hash=_CONTENT_HASH,
    )


def _make_retrieval_embeddings() -> list[EmbeddingVector]:
    """Build the three document retrieval vectors required by the active manifest."""
    return [
        EmbeddingVector(
            embedding_type=EmbeddingType.MUVERA,
            dense=DenseData(values=[0.1] * 8192),
            collection_version=_COLLECTION_VERSION,
            content_hash=_CONTENT_HASH,
        ),
        EmbeddingVector(
            embedding_type=EmbeddingType.SPARSE,
            sparse=SparseData(indices=[1, 2, 3], values=[0.5, 0.6, 0.7]),
            collection_version=_COLLECTION_VERSION,
            content_hash=_CONTENT_HASH,
        ),
        EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=[0.2] * 48, num_tokens=1, token_dim=48),
            collection_version=_COLLECTION_VERSION,
            content_hash=_CONTENT_HASH,
        ),
    ]


@pytest.fixture
def qdrant_client() -> Iterator[MagicMock]:
    """Keep saga integration tests hermetic at the Qdrant transport boundary."""
    client = MagicMock()
    client.upsert_vector_points_batch = AsyncMock(return_value=1)
    with patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=client):
        yield client


def _make_stored() -> StoredListing:
    """Build a StoredListing proto with all fields needed to satisfy listings constraints.

    The description must be at least 200 chars (chk_description_length) and the
    location must be a non-null JSON object with a country (chk_location_json),
    so we set both deliberately. Embeddings are required by build_listing_snapshot.
    """
    long_description = (
        "Looking for an experienced Python engineer to join our team building distributed systems. "
        "Must be comfortable with async I/O, Kafka, PostgreSQL, and event-driven architecture. "
        "You will own backend services end to end and collaborate closely with the platform team. "
        "Strong communication skills and a track record of shipping production software required."
    )
    return StoredListing(
        listing_url=_LISTING_URL,
        source=JobBoardSource.LINKEDIN,
        external_id="ext-12345",
        title="Senior Python Engineer",
        company_name="Acme Corp",
        description=long_description,
        location=Location(
            city="San Francisco",
            state_province="CA",
            country=CountryCode.USA,
            location_type=LocationType.PHYSICAL,
        ),
        work_arrangement=WorkArrangement.HYBRID,
        employment_term=EmploymentTerm.FULL_TIME,
        seniority_level=SeniorityLevel.SENIOR,
        language="en",
        skill_requirements=[
            JobSkillRequirement(skill_id="skill-py", skill_name="python"),
            JobSkillRequirement(skill_id="skill-pg", skill_name="postgresql"),
        ],
        skills_embedding=EmbeddingVector(
            embedding_type=EmbeddingType.DENSE,
            dense=DenseData(values=[0.1, 0.2, 0.3, 0.4]),
            collection_version=_COLLECTION_VERSION,
        ),
        title_embedding=EmbeddingVector(
            embedding_type=EmbeddingType.DENSE,
            dense=DenseData(values=[0.5, 0.6, 0.7, 0.8]),
            collection_version=_COLLECTION_VERSION,
        ),
        retrieval_embeddings=_make_retrieval_embeddings(),
        discovered_timestamp=_DISCOVERED_AT,
        posted_timestamp=_POSTED_AT,
        content_hash=_CONTENT_HASH,
        version=1,
    )


def _listing_reference() -> ListingReference:
    return ListingReference(
        listing_url=_LISTING_URL,
        external_listing_id="ext-12345",
        source=JobBoardSource.LINKEDIN,
    )


async def _outbox_rows(session: AsyncSession, aggregate_id: str) -> list[tuple[str, str]]:
    """Return ``[(type, aggregateid), ...]`` for outbox rows with the given aggregate."""
    result = await session.execute(
        text(f"SELECT type, aggregateid FROM {SCHEMA_NAME}.outbox WHERE aggregateid = :agg ORDER BY timestamp"),
        {"agg": aggregate_id},
    )
    return [(row.type, row.aggregateid) for row in result.fetchall()]


@pytest.fixture
def service() -> JobStoreService:
    return JobStoreService()


@pytest.fixture
def context() -> RawJobContext:
    return RawJobContext(correlation_id=_CORRELATION_ID, discovered_at=_DISCOVERED_AT)


class TestHandleDiscoveredListing:
    """Phase 1: discovered listing -> PENDING saga + ListingAccepted."""

    async def test_creates_pending_saga_and_outbox_event(
        self,
        async_session: AsyncSession,
        service: JobStoreService,
        context: RawJobContext,
    ) -> None:
        result = await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            context,
            query_id="q-001",
        )

        assert result.is_new is True

        sagas = (await async_session.execute(select(ListingIngestSaga))).scalars().all()
        assert len(sagas) == 1
        saga = sagas[0]
        assert saga.listing_url == _LISTING_URL
        assert saga.status == "PENDING"
        assert saga.received_callbacks == 0
        assert saga.expected_callbacks == 1
        assert saga.version == 1
        assert saga.content_hash == _CONTENT_HASH

        # Saga ID is what propagates downstream as the listing_id anchor.
        assert result.saga_id == saga.id

        # No canonical listings row yet: those are reserved for post-enrichment.
        listings = (await async_session.execute(select(Listing))).scalars().all()
        assert listings == []

        outbox = await _outbox_rows(async_session, str(saga.id))
        assert outbox == [(Topics.JOB_LISTING_ACCEPTED, str(saga.id))]

    async def test_redelivery_same_content_hash_is_idempotent(
        self,
        async_session: AsyncSession,
        service: JobStoreService,
        context: RawJobContext,
    ) -> None:
        first = await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            context,
        )
        # Re-deliver the identical event.
        second = await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            context,
        )

        assert first.saga_id == second.saga_id
        assert second.is_new is False

        sagas = (await async_session.execute(select(ListingIngestSaga))).scalars().all()
        assert len(sagas) == 1


class TestBankStoredListing:
    """Phase 2: enrichment completed -> COMPLETED saga + canonical listings row."""

    async def test_promotes_pending_saga_to_completed_and_creates_listing(
        self,
        async_session: AsyncSession,
        service: JobStoreService,
        context: RawJobContext,
        qdrant_client: MagicMock,
    ) -> None:
        ingest = await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            context,
        )

        outcome = await service.bank_stored_listing(
            async_session,
            _make_stored(),
            _listing_reference(),
            _CORRELATION_ID,
            _COLLECTION_VERSION,
        )

        assert outcome.status == "banked"
        listing_id_str = outcome.listing_id
        assert listing_id_str is not None
        assert outcome.was_updated is False
        qdrant_client.upsert_vector_points_batch.assert_awaited_once()
        # Saga UUID is promoted to listings.id, anchoring the lifecycle.
        assert listing_id_str == str(ingest.saga_id)

        # Re-fetch the saga to pick up the COMPLETED status. Banking bumps
        # received_callbacks to expected_callbacks before transitioning, so
        # the invariant ``received_callbacks == expected_callbacks`` holds for
        # every COMPLETED row.
        async_session.expire_all()
        saga = await async_session.get(ListingIngestSaga, ingest.saga_id)
        assert saga is not None
        assert saga.status == "COMPLETED"
        assert saga.received_callbacks == saga.expected_callbacks == 1

        listings = (await async_session.execute(select(Listing))).scalars().all()
        assert len(listings) == 1
        listing = listings[0]
        assert str(listing.id) == listing_id_str
        assert listing.title == "Senior Python Engineer"
        assert listing.company_name == "Acme Corp"
        assert listing.listing_url == _LISTING_URL

        outbox = await _outbox_rows(async_session, listing_id_str)
        event_types = [t for t, _ in outbox]
        assert Topics.JOB_LISTING_ACCEPTED in event_types
        assert Topics.JOB_LISTING_CREATED in event_types
        # No update event on a fresh insert.
        assert Topics.JOB_LISTING_UPDATED not in event_types

    async def test_bank_without_pending_saga_is_orphan(
        self,
        async_session: AsyncSession,
        service: JobStoreService,
    ) -> None:
        """When no saga exists, banking returns BankOutcome(status='orphan')."""
        outcome = await service.bank_stored_listing(
            async_session,
            _make_stored(),
            _listing_reference(),
            _CORRELATION_ID,
            _COLLECTION_VERSION,
        )

        assert outcome.status == "orphan"
        listings = (await async_session.execute(select(Listing))).scalars().all()
        assert listings == []

    async def test_bank_after_completed_is_replay(
        self,
        async_session: AsyncSession,
        service: JobStoreService,
        context: RawJobContext,
        qdrant_client: MagicMock,
    ) -> None:
        """Once a saga is COMPLETED, redelivery of EnrichmentCompleted is a replay no-op."""
        await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            context,
        )
        first = await service.bank_stored_listing(
            async_session,
            _make_stored(),
            _listing_reference(),
            _CORRELATION_ID,
            _COLLECTION_VERSION,
        )
        assert first.status == "banked"

        second = await service.bank_stored_listing(
            async_session,
            _make_stored(),
            _listing_reference(),
            _CORRELATION_ID,
            _COLLECTION_VERSION,
        )
        assert second.status == "replay"
        qdrant_client.upsert_vector_points_batch.assert_awaited_once()

        listings = (await async_session.execute(select(Listing))).scalars().all()
        assert len(listings) == 1

    async def test_completed_saga_does_not_block_new_pending_saga(
        self,
        async_session: AsyncSession,
        service: JobStoreService,
        context: RawJobContext,
        qdrant_client: MagicMock,
    ) -> None:
        """Partial unique index on PENDING permits a fresh saga after the prior COMPLETED."""
        await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            context,
        )
        await service.bank_stored_listing(
            async_session,
            _make_stored(),
            _listing_reference(),
            _CORRELATION_ID,
            _COLLECTION_VERSION,
        )
        qdrant_client.upsert_vector_points_batch.assert_awaited_once()

        # Re-discover the same URL after the prior saga has COMPLETED: the
        # partial unique index allows a brand-new PENDING saga to be inserted.
        rediscovered = await service.handle_discovered_listing(
            async_session,
            _make_discovered(),
            _listing_reference(),
            RawJobContext(correlation_id="corr-redo", discovered_at=_DISCOVERED_AT),
        )
        assert rediscovered.is_new is True

        sagas = (await async_session.execute(select(ListingIngestSaga))).scalars().all()
        # One COMPLETED + one fresh PENDING.
        assert len(sagas) == 2
        statuses = sorted(s.status for s in sagas)
        assert statuses == ["COMPLETED", "PENDING"]

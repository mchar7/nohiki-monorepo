"""Unit tests for services/bank_service.py module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from job_storage_service.db.models import Listing
from job_storage_service.services.bank_service import (
    JobStoreService,
    RawJobContext,
)
from nohiki.common.v1 import (
    CountryCode,
    JobBoardSource,
    ListingStatus,
    Location,
    LocationType,
)
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, MultiVectorData, SparseData


def _create_test_retrieval_embeddings() -> list[EmbeddingVector]:
    """Create test retrieval embeddings for ECST compliance."""
    return [
        EmbeddingVector(
            embedding_type=EmbeddingType.MUVERA,
            dense=DenseData(values=[0.1] * 100),
        ),
        EmbeddingVector(
            embedding_type=EmbeddingType.SPARSE,
            sparse=SparseData(indices=[1, 2, 3], values=[0.5, 0.6, 0.7]),
        ),
        EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=[0.1] * 48, num_tokens=1, token_dim=48),
        ),
    ]


def _create_test_skills_embedding() -> EmbeddingVector:
    """Create test skills embedding."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=[0.1] * 100),
    )


def _create_test_title_embedding() -> EmbeddingVector:
    """Create test title embedding."""
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=[0.2] * 100),
    )


class TestJobStoreService:
    """Tests for JobStoreService class."""

    @pytest.fixture
    def service(self) -> JobStoreService:
        """Create a JobStoreService instance."""
        return JobStoreService()

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create a mock database session.

        AsyncSession has both sync (add, delete, expunge) and async (execute,
        commit) methods. Sync methods must be MagicMock to avoid unawaited
        coroutine warnings.
        """
        mock = AsyncMock()
        mock.add = MagicMock()
        mock.delete = MagicMock()
        mock.expunge = MagicMock()
        return mock

    @pytest.fixture
    def sample_listing(self) -> Listing:
        """Create a sample Listing for testing (with required embeddings)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        return Listing(
            id=uuid.uuid4(),
            listing_url="https://example.com/job/123",
            job_board_source=JobBoardSource.INDEED,
            title="Senior Python Developer",
            company_name="Acme Corp",
            version=1,
            raw_content_hash="abc123",
            discovered_at=now,
            created_at=now,
            updated_at=now,
            status=ListingStatus.ACTIVE,
            skills_embedding=[0.1, 0.2, 0.3],
            title_embedding=[0.1, 0.2, 0.3],
            collection_version="test-v1",
        )

    @pytest.mark.asyncio
    async def test_get_job_by_id(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test getting a job by ID."""
        expected_job = MagicMock(spec=Listing)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = expected_job
        mock_db.execute.return_value = mock_result

        result = await service.get_job_by_id(mock_db, "test-id")

        assert result == expected_job
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_job_by_id_not_found(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test getting a job by ID that doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_job_by_id(mock_db, "nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_jobs_by_ids(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test getting multiple jobs by IDs."""
        jobs = [MagicMock(spec=Listing), MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.get_jobs_by_ids(mock_db, ["id1", "id2"])

        assert len(result) == 2
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_recent_jobs(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test getting recently scraped jobs."""
        jobs = [MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.get_recent_jobs(mock_db, hours=48, limit=50)

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_listings_for_backfill(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test getting listings for profile backfill."""
        jobs = [MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.get_listings_for_backfill(mock_db, max_listings=100, since_days=14)

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_jobs_by_location_with_city(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test searching jobs by city."""
        jobs = [MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.get_jobs_by_location(mock_db, city="San Francisco")

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_jobs_by_location_with_state(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test searching jobs by state."""
        jobs = [MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.get_jobs_by_location(mock_db, state="California")

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_jobs_by_location_with_country(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test searching jobs by country."""
        jobs = [MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.get_jobs_by_location(mock_db, country="USA")

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_jobs_by_location_no_conditions(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test searching jobs with no location conditions returns empty list."""
        result = await service.get_jobs_by_location(mock_db)

        assert result == []
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_job(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test deleting a job."""
        from unittest.mock import patch

        qdrant = MagicMock()
        qdrant.delete_points = AsyncMock()
        mock_db.execute.return_value = MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )

        with patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant):
            await service.delete_job(mock_db, "test-id")

        assert mock_db.execute.await_count >= 1
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_jobs_fts(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test full-text search for jobs."""
        mock_job = MagicMock(spec=Listing)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_job]
        mock_db.execute.return_value = mock_result

        result = await service.search_jobs_fts(mock_db, query="python developer", limit=10)

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_jobs_by_skills(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Test searching jobs by skills."""
        jobs = [MagicMock(spec=Listing)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = jobs
        mock_db.execute.return_value = mock_result

        result = await service.search_jobs_by_skills(mock_db, skills=["python", "django"], limit=10)

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_discovered_listing_new_saga(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """A discovered listing with no in-flight saga creates a new saga row."""
        from unittest.mock import patch

        from nohiki.common.v1 import ListingReference
        from nohiki.job.ingest.v1 import DiscoveredListing

        mock_no_existing = MagicMock()
        mock_no_existing.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_no_existing

        discovered = DiscoveredListing(
            listing_url="https://example.com/job/123",
            content_hash="abc123",
        )
        listing_reference = ListingReference(listing_url="https://example.com/job/123")
        context = RawJobContext(correlation_id="test-correlation", discovered_at=datetime.now(UTC))

        created_saga = MagicMock()
        created_saga.id = uuid.uuid4()

        with (
            patch("job_storage_service.services.bank_service._saga_repo") as mock_repo,
            patch(
                "job_storage_service.services.bank_service.publish_listing_accepted_event",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.create = AsyncMock(return_value=created_saga)

            result = await service.handle_discovered_listing(mock_db, discovered, listing_reference, context)

        assert result.is_new is True
        assert result.saga_id == created_saga.id
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bank_stored_listing_update_existing(
        self, service: JobStoreService, mock_db: AsyncMock, sample_listing: Listing
    ) -> None:
        """Banking promotes a PENDING saga and merges enrichment onto a cross-source duplicate."""
        from unittest.mock import patch

        from nohiki.common.v1 import ListingReference
        from nohiki.job.ingest.v1 import StoredListing

        sample_listing.discovered_at = datetime.now(UTC)
        sample_listing.created_at = datetime.now(UTC)
        sample_listing.updated_at = datetime.now(UTC)
        sample_listing.dedup_hash = "test-dedup-hash"

        saga = MagicMock()
        saga.id = sample_listing.id
        saga.version = 1
        saga.expected_callbacks = 1
        saga.content_hash = "abc123"
        saga.transition_to = MagicMock()

        mock_row = MagicMock()
        mock_row.id = sample_listing.id

        # Sequence: pending-saga lookup (FOR UPDATE), dedup-hash lookup
        # (cross-source hit; URL fallback short-circuits via ``or``), UPDATE
        # returning, post-update get_by_id, saga COMPLETED UPDATE.
        mock_pending = MagicMock()
        mock_pending.scalar_one_or_none.return_value = saga

        mock_dedup_hit = MagicMock()
        mock_dedup_hit.scalar_one_or_none.return_value = sample_listing

        mock_update = MagicMock()
        mock_update.fetchone.return_value = mock_row

        mock_get_by_id = MagicMock()
        mock_get_by_id.scalar_one_or_none.return_value = sample_listing

        mock_saga_complete = MagicMock()
        mock_saga_complete.rowcount = 1

        mock_db.execute.side_effect = [
            mock_pending,
            mock_dedup_hit,
            mock_update,
            mock_get_by_id,
            mock_saga_complete,
        ]

        stored = StoredListing(
            listing_url="https://example.com/job/123",
            content_hash="abc123",
            description="x" * 250,
            location=_make_location(),
            skills_embedding=_create_test_skills_embedding(),
            title_embedding=_create_test_title_embedding(),
            retrieval_embeddings=_create_test_retrieval_embeddings(),
        )
        listing_reference = ListingReference(listing_url="https://example.com/job/123")
        qdrant = MagicMock()
        qdrant.upsert_vector_points_batch = AsyncMock(return_value=1)

        with (
            patch("job_storage_service.services.bank_service.publish_listing_created_event", new_callable=AsyncMock),
            patch("job_storage_service.services.bank_service.publish_listing_updated_event", new_callable=AsyncMock),
            patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant),
        ):
            outcome = await service.bank_stored_listing(
                mock_db, stored, listing_reference, correlation_id="test-correlation", collection_version="v1"
            )

        assert outcome.status == "banked"
        assert outcome.listing_id == str(sample_listing.id)
        assert outcome.was_updated is True
        saga.transition_to.assert_not_called()  # banking uses optimistic UPDATE, not in-memory transition
        mock_db.commit.assert_awaited_once()
        qdrant.upsert_vector_points_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bank_stored_listing_orphan_when_no_saga(self, service: JobStoreService, mock_db: AsyncMock) -> None:
        """Without a PENDING saga the call returns BankOutcome(status='orphan')."""
        from nohiki.common.v1 import ListingReference
        from nohiki.job.ingest.v1 import StoredListing

        mock_no_saga = MagicMock()
        mock_no_saga.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_no_saga

        stored = StoredListing(
            listing_url="https://example.com/job/orphan",
            content_hash="orphan-hash",
            description="x" * 250,
            location=_make_location(),
            skills_embedding=_create_test_skills_embedding(),
            title_embedding=_create_test_title_embedding(),
        )
        listing_reference = ListingReference(listing_url="https://example.com/job/orphan")

        outcome = await service.bank_stored_listing(
            mock_db, stored, listing_reference, correlation_id="corr", collection_version="v1"
        )

        assert outcome.status == "orphan"
        mock_db.commit.assert_not_awaited()


def _make_location() -> Location:
    """Construct a Location proto satisfying the listings table CHECK constraints."""
    return Location(country=CountryCode.USA, location_type=LocationType.PHYSICAL)


class TestRawJobContext:
    """Tests for RawJobContext dataclass."""

    def test_create_raw_job_context(self) -> None:
        """Test creating a RawJobContext instance."""
        correlation_id = str(uuid.uuid4())
        discovered_at = datetime.now(UTC)

        ctx = RawJobContext(correlation_id=correlation_id, discovered_at=discovered_at)

        assert ctx.correlation_id == correlation_id
        assert ctx.discovered_at == discovered_at

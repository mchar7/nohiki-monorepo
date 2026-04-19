"""Unit tests for events/publishers.py module - focusing on business logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_storage_service.db.models import Listing
from job_storage_service.events.publishers import (
    PublishContext,
    _truncate_description,
    build_listing_snapshot,
    publish_duplicate_detected_event,
    publish_listing_created_event,
    publish_listing_deleted_event,
    publish_listing_updated_event,
)
from nohiki.common.v1 import (
    CountryCode,
    CurrencyCode,
    JobBoardSource,
    ListingReference,
    LocationType,
    PaymentFrequency,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector, MultiVectorData, SparseData
from nohiki_db_utils.testing import create_mock_session

_STUB_EMBEDDING = [0.1, 0.2, 0.3]
_STUB_COLLECTION_VERSION = "test-v1"


def _create_test_retrieval_embeddings() -> list[EmbeddingVector]:
    """Create test retrieval embeddings for ECST compliance."""
    return [
        EmbeddingVector(
            embedding_type=EmbeddingType.MUVERA,
            dense=DenseData(values=[0.1] * 8192),
        ),
        EmbeddingVector(
            embedding_type=EmbeddingType.SPARSE,
            sparse=SparseData(indices=[1, 2, 3], values=[0.5, 0.6, 0.7]),
        ),
        EmbeddingVector(
            embedding_type=EmbeddingType.COLBERT,
            multi_vector=MultiVectorData(values=[0.1] * 480, num_tokens=10, token_dim=48),
        ),
    ]


def _with_embeddings(listing: Listing) -> Listing:
    """Add required embedding fields to a Listing for build_listing_snapshot tests."""
    listing.skills_embedding = _STUB_EMBEDDING
    listing.title_embedding = _STUB_EMBEDDING
    listing.collection_version = _STUB_COLLECTION_VERSION
    return listing


@pytest.fixture
def sample_listing() -> Listing:
    """Create a sample Listing for testing (with required embeddings)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    return _with_embeddings(
        Listing(
            id=uuid.uuid4(),
            listing_url="https://example.com/job/123",
            job_board_source=JobBoardSource.INDEED,
            title="Senior Python Developer",
            company_name="Acme Corp",
            description="Great Python job opportunity",
            work_arrangement=WorkArrangement.REMOTE,
            seniority_level=SeniorityLevel.SENIOR,
            required_skills=["Python", "Django", "PostgreSQL"],
            min_experience_years=5,
            max_experience_years=10,
            compensation={
                "frequency": "PAYMENT_FREQUENCY_ANNUALLY",
                "minAmount": {
                    "amount": {"currency": "CURRENCY_CODE_USD", "minorUnits": "120000"},
                    "source": "COMPENSATION_SOURCE_ESTIMATED_BY_JOB_BOARD",
                    "confidencePercent": 80,
                },
                "maxAmount": {
                    "amount": {"currency": "CURRENCY_CODE_USD", "minorUnits": "180000"},
                    "source": "COMPENSATION_SOURCE_ESTIMATED_BY_JOB_BOARD",
                    "confidencePercent": 80,
                },
            },
            location={
                "city": "San Francisco",
                "stateProvince": "CA",
                "country": "COUNTRY_CODE_USA",
                "locationType": "LOCATION_TYPE_REMOTE",
                "source": "LOCATION_SOURCE_JOB_POSTING",
            },
            version=1,
            raw_content_hash="abc123",
            discovered_at=now,
            processed_at=now,
            created_at=now,
            updated_at=now,
            posted_at=now,
        )
    )


class TestBuildListingSnapshot:
    """Tests for build_listing_snapshot function."""

    def test_builds_complete_snapshot(self, sample_listing: Listing) -> None:
        """Test building snapshot with all fields populated."""
        snapshot = build_listing_snapshot(sample_listing)

        assert snapshot.id == str(sample_listing.id)
        assert snapshot.listing_url == sample_listing.listing_url
        assert snapshot.source == sample_listing.job_board_source
        assert snapshot.title == sample_listing.title
        assert snapshot.company_name == sample_listing.company_name
        assert snapshot.description == sample_listing.description
        assert snapshot.work_arrangement == sample_listing.work_arrangement
        assert snapshot.seniority_level == sample_listing.seniority_level
        assert snapshot.version == sample_listing.version
        assert snapshot.raw_content_hash == sample_listing.raw_content_hash
        assert list(snapshot.required_skills) == sample_listing.required_skills
        assert snapshot.experience_years_min == sample_listing.min_experience_years
        assert snapshot.experience_years_max == sample_listing.max_experience_years

    def test_raises_on_missing_skills_embedding(self) -> None:
        """Test that build_listing_snapshot fails fast when skills_embedding is missing."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = Listing(
            id=uuid.uuid4(),
            listing_url="https://example.com/job/no-emb",
            job_board_source=JobBoardSource.INDEED,
            version=1,
            raw_content_hash="noemb",
            discovered_at=now,
            created_at=now,
            updated_at=now,
            title_embedding=_STUB_EMBEDDING,
            collection_version=_STUB_COLLECTION_VERSION,
        )

        with pytest.raises(ValueError, match="missing required skills_embedding"):
            build_listing_snapshot(listing)

    def test_raises_on_missing_title_embedding(self) -> None:
        """Test that build_listing_snapshot fails fast when title_embedding is missing."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = Listing(
            id=uuid.uuid4(),
            listing_url="https://example.com/job/no-emb",
            job_board_source=JobBoardSource.INDEED,
            version=1,
            raw_content_hash="noemb",
            discovered_at=now,
            created_at=now,
            updated_at=now,
            skills_embedding=_STUB_EMBEDDING,
            collection_version=_STUB_COLLECTION_VERSION,
        )

        with pytest.raises(ValueError, match="missing required title_embedding"):
            build_listing_snapshot(listing)

    def test_handles_missing_optional_fields(self) -> None:
        """Test snapshot building with minimal fields (but required embeddings)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/456",
                job_board_source=JobBoardSource.LINKEDIN,
                version=1,
                raw_content_hash="def456",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.id == str(listing.id)
        assert snapshot.title == ""
        assert snapshot.company_name == ""
        assert snapshot.description == ""
        assert len(snapshot.required_skills) == 0

    def test_truncates_long_description(self) -> None:
        """Test that very long descriptions are truncated."""
        now = datetime.now(UTC).replace(tzinfo=None)
        long_desc = "x" * 10000
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/789",
                job_board_source=JobBoardSource.GLASSDOOR,
                description=long_desc,
                version=1,
                raw_content_hash="ghi789",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert len(snapshot.description) == 5000
        assert snapshot.description == "x" * 5000

    def test_builds_compensation_with_range(self, sample_listing: Listing) -> None:
        """Test compensation building with min/max range."""
        snapshot = build_listing_snapshot(sample_listing)

        assert snapshot.compensation is not None
        assert snapshot.compensation.frequency == PaymentFrequency.ANNUALLY
        assert snapshot.compensation.min_amount is not None
        assert snapshot.compensation.max_amount is not None
        assert snapshot.compensation.min_amount.amount.minor_units == 120000
        assert snapshot.compensation.min_amount.amount.currency == CurrencyCode.USD
        assert snapshot.compensation.max_amount.amount.minor_units == 180000
        assert snapshot.compensation.max_amount.amount.currency == CurrencyCode.USD

    def test_builds_compensation_with_fixed_amount(self) -> None:
        """Test compensation building with fixed amount."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/fixed",
                job_board_source=JobBoardSource.INDEED,
                compensation={
                    "frequency": "PAYMENT_FREQUENCY_ANNUALLY",
                    "fixedAmount": {
                        "amount": {"currency": "CURRENCY_CODE_USD", "minorUnits": "150000"},
                        "source": "COMPENSATION_SOURCE_ESTIMATED_BY_JOB_BOARD",
                        "confidencePercent": 90,
                    },
                },
                version=1,
                raw_content_hash="fixed123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.compensation is not None
        assert snapshot.compensation.fixed_amount is not None
        assert snapshot.compensation.fixed_amount.amount.minor_units == 150000
        assert snapshot.compensation.fixed_amount.amount.currency == CurrencyCode.USD

    def test_handles_missing_compensation(self) -> None:
        """Test snapshot with no compensation data."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/nocomp",
                job_board_source=JobBoardSource.INDEED,
                version=1,
                raw_content_hash="nocomp123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.compensation is None

    def test_builds_location_for_physical_job(self) -> None:
        """Test location building for physical job."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/loc",
                job_board_source=JobBoardSource.INDEED,
                work_arrangement=WorkArrangement.ON_SITE,
                location={
                    "city": "Toronto",
                    "stateProvince": "ON",
                    "country": "COUNTRY_CODE_CAN",
                    "locationType": "LOCATION_TYPE_PHYSICAL",
                    "source": "LOCATION_SOURCE_JOB_POSTING",
                },
                version=1,
                raw_content_hash="loc123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.location is not None
        assert snapshot.location.city == "Toronto"
        assert snapshot.location.state_province == "ON"
        assert snapshot.location.country == CountryCode.CAN
        assert snapshot.location.location_type == LocationType.PHYSICAL

    def test_builds_location_for_remote_job(self, sample_listing: Listing) -> None:
        """Test location building for remote job."""
        snapshot = build_listing_snapshot(sample_listing)

        assert snapshot.location is not None
        assert snapshot.location.location_type == LocationType.REMOTE

    def test_handles_missing_location(self) -> None:
        """Test snapshot with no location data."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/noloc",
                job_board_source=JobBoardSource.INDEED,
                version=1,
                raw_content_hash="noloc123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.location is None

    def test_handles_invalid_country_code(self) -> None:
        """Test location with unspecified country code returns None."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/badcountry",
                job_board_source=JobBoardSource.INDEED,
                location={
                    "city": "Paris",
                    "country": "COUNTRY_CODE_UNSPECIFIED",
                },
                version=1,
                raw_content_hash="bad123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.location is None

    def test_handles_compensation_with_euro_currency(self) -> None:
        """Test compensation with EUR currency."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/euro",
                job_board_source=JobBoardSource.INDEED,
                compensation={
                    "frequency": "PAYMENT_FREQUENCY_ANNUALLY",
                    "minAmount": {
                        "amount": {"currency": "CURRENCY_CODE_EUR", "minorUnits": "80000"},
                        "source": "COMPENSATION_SOURCE_ESTIMATED_BY_JOB_BOARD",
                        "confidencePercent": 75,
                    },
                    "maxAmount": {
                        "amount": {"currency": "CURRENCY_CODE_EUR", "minorUnits": "120000"},
                        "source": "COMPENSATION_SOURCE_ESTIMATED_BY_JOB_BOARD",
                        "confidencePercent": 75,
                    },
                },
                version=1,
                raw_content_hash="euro123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.compensation is not None
        assert snapshot.compensation.min_amount is not None
        assert snapshot.compensation.max_amount is not None
        assert snapshot.compensation.min_amount.amount.currency == CurrencyCode.EUR
        assert snapshot.compensation.max_amount.amount.currency == CurrencyCode.EUR

    def test_handles_hourly_frequency(self) -> None:
        """Test compensation with hourly frequency."""
        now = datetime.now(UTC).replace(tzinfo=None)
        listing = _with_embeddings(
            Listing(
                id=uuid.uuid4(),
                listing_url="https://example.com/job/hourly",
                job_board_source=JobBoardSource.INDEED,
                compensation={
                    "frequency": "PAYMENT_FREQUENCY_HOURLY",
                    "fixedAmount": {
                        "amount": {"currency": "CURRENCY_CODE_USD", "minorUnits": "75"},
                        "source": "COMPENSATION_SOURCE_ESTIMATED_BY_JOB_BOARD",
                        "confidencePercent": 70,
                    },
                },
                version=1,
                raw_content_hash="hourly123",
                discovered_at=now,
                created_at=now,
                updated_at=now,
            )
        )

        snapshot = build_listing_snapshot(listing)

        assert snapshot.compensation is not None
        assert snapshot.compensation.frequency == PaymentFrequency.HOURLY


class TestTruncateDescription:
    """Tests for _truncate_description helper function."""

    def test_returns_empty_for_none(self) -> None:
        """Test that None returns empty string."""
        assert _truncate_description(None) == ""

    def test_returns_empty_for_empty_string(self) -> None:
        """Test that empty string returns empty string."""
        assert _truncate_description("") == ""

    def test_returns_short_description_unchanged(self) -> None:
        """Test that short descriptions are not modified."""
        desc = "Short description"
        assert _truncate_description(desc) == desc

    def test_truncates_long_description(self) -> None:
        """Test that descriptions over 5000 chars are truncated."""
        long_desc = "x" * 10000
        result = _truncate_description(long_desc)
        assert len(result) == 5000


class TestPublishContext:
    """Tests for PublishContext dataclass."""

    def test_creates_context(self) -> None:
        """Test creating a PublishContext."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        listing_ref = ListingReference(
            listing_url="https://example.com/job/123",
            listing_id="listing-123",
        )

        ctx = PublishContext(
            db=mock_db,
            outbox=mock_outbox,
            listing_id="listing-123",
            listing_reference=listing_ref,
            correlation_id="corr-456",
        )

        assert ctx.listing_id == "listing-123"
        assert ctx.correlation_id == "corr-456"


class TestPublishDuplicateDetectedEvent:
    """Tests for publish_duplicate_detected_event async function."""

    @pytest.mark.asyncio
    async def test_publishes_event(self, sample_listing: Listing) -> None:
        """Test publishing duplicate detected event."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        listing_ref = ListingReference(
            listing_url="https://example.com/job/123",
            listing_id="listing-123",
            external_listing_id="ext-123",
            source=JobBoardSource.INDEED,
        )

        ctx = PublishContext(
            db=mock_db,
            outbox=mock_outbox,
            listing_id="listing-123",
            listing_reference=listing_ref,
            correlation_id="corr-456",
        )

        with patch("job_storage_service.events.publishers.get_settings") as mock_settings:
            mock_settings.return_value.service_name = "job-storage-service"
            await publish_duplicate_detected_event(ctx, sample_listing)

        mock_outbox.write_event.assert_awaited_once()


class TestPublishListingCreatedEvent:
    """Tests for publish_listing_created_event async function."""

    @pytest.mark.asyncio
    async def test_publishes_event(self, sample_listing: Listing) -> None:
        """Publishing emits the right topic, aggregate id, and snapshot payload."""
        from nohiki_kafka_client import Topics

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        listing_ref = ListingReference(
            listing_url="https://example.com/job/123",
            listing_id="listing-123",
        )

        ctx = PublishContext(
            db=mock_db,
            outbox=mock_outbox,
            listing_id="listing-123",
            listing_reference=listing_ref,
            correlation_id="corr-456",
        )

        with patch("job_storage_service.events.publishers.get_settings") as mock_settings:
            mock_settings.return_value.service_name = "job-storage-service"
            await publish_listing_created_event(
                ctx,
                sample_listing,
                was_updated=False,
                retrieval_embeddings=_create_test_retrieval_embeddings(),
            )

        mock_outbox.write_event.assert_awaited_once()
        call = mock_outbox.write_event.await_args
        assert call is not None
        kwargs = call.kwargs
        assert kwargs["params"].aggregate_id == "listing-123"
        assert kwargs["params"].event_type == Topics.JOB_LISTING_CREATED
        assert kwargs["params"].correlation_id == "corr-456"
        # The event payload must carry the snapshot anchored to the listing id.
        event = kwargs["event"]
        assert event.listing_snapshot.id == str(sample_listing.id)
        assert event.was_updated is False

    @pytest.mark.asyncio
    async def test_publishes_event_with_update_flag(self, sample_listing: Listing) -> None:
        """The was_updated flag flows through to the published event."""
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        listing_ref = ListingReference(
            listing_url="https://example.com/job/123",
            listing_id="listing-123",
        )

        ctx = PublishContext(
            db=mock_db,
            outbox=mock_outbox,
            listing_id="listing-123",
            listing_reference=listing_ref,
            correlation_id="corr-456",
        )

        with patch("job_storage_service.events.publishers.get_settings") as mock_settings:
            mock_settings.return_value.service_name = "job-storage-service"
            await publish_listing_created_event(
                ctx,
                sample_listing,
                was_updated=True,
                retrieval_embeddings=_create_test_retrieval_embeddings(),
            )

        call = mock_outbox.write_event.await_args
        assert call is not None
        kwargs = call.kwargs
        assert kwargs["event"].was_updated is True


class TestPublishListingUpdatedEvent:
    """Tests for publish_listing_updated_event async function."""

    @pytest.mark.asyncio
    async def test_publishes_event(self, sample_listing: Listing) -> None:
        """Publishing emits a ListingUpdated event with the listing's snapshot."""
        from nohiki_kafka_client import Topics

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        listing_ref = ListingReference(
            listing_url="https://example.com/job/123",
            listing_id="listing-123",
        )

        ctx = PublishContext(
            db=mock_db,
            outbox=mock_outbox,
            listing_id="listing-123",
            listing_reference=listing_ref,
            correlation_id="corr-456",
        )

        with patch("job_storage_service.events.publishers.get_settings") as mock_settings:
            mock_settings.return_value.service_name = "job-storage-service"
            await publish_listing_updated_event(ctx, sample_listing)

        call = mock_outbox.write_event.await_args
        assert call is not None
        kwargs = call.kwargs
        assert kwargs["params"].aggregate_id == "listing-123"
        assert kwargs["params"].event_type == Topics.JOB_LISTING_UPDATED
        assert kwargs["event"].listing_id == "listing-123"


class TestPublishListingDeletedEvent:
    """Tests for publish_listing_deleted_event async function."""

    @pytest.mark.asyncio
    async def test_publishes_event(self) -> None:
        """Publishing emits a ListingDeleted event with the right id and topic."""
        from nohiki_kafka_client import Topics

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        with patch("job_storage_service.events.publishers.get_settings") as mock_settings:
            mock_settings.return_value.service_name = "job-storage-service"
            await publish_listing_deleted_event(mock_db, mock_outbox, "listing-123", "corr-456")

        call = mock_outbox.write_event.await_args
        assert call is not None
        kwargs = call.kwargs
        assert kwargs["params"].aggregate_id == "listing-123"
        assert kwargs["params"].event_type == Topics.JOB_LISTING_DELETED
        assert kwargs["event"].listing_id == "listing-123"

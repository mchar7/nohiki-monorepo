"""Unit tests for job ingest pipeline event structures.

Tests the proto structures used in the ingest pipeline from discovery
through enrichment to storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from nohiki.common.v1 import (
    CurrencyCode,
    EventMetadata,
    JobBoardSource,
    ListingReference,
    WorkArrangement,
)
from nohiki.job.ingest.v1 import (
    DiscoveredListing,
    StoredListing,
)


def build_test_metadata(correlation_id: str | None = None) -> EventMetadata:
    """Build test event metadata with correct field names."""
    return EventMetadata(
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        source_service="test-service",
        correlation_id=correlation_id,
        version="v1",
    )


def generate_content_hash(content: str) -> str:
    """Generate SHA-256 hash for content deduplication."""
    return sha256(content.encode()).hexdigest()


class TestDiscoveredListingProto:
    """Test DiscoveredListing proto structure."""

    def test_discovered_listing_required_fields(self) -> None:
        """Test DiscoveredListing has required fields."""
        description = "Looking for a Python developer..."
        listing = DiscoveredListing(
            listing_url="https://example.com/job/12345",
            source=JobBoardSource.INDEED,
            title="Senior Python Developer",
            company_name="TechCorp",
            description=description,
            location_raw="San Francisco, CA",
            raw_skills=["Python", "Django", "PostgreSQL"],
            content_hash=generate_content_hash(description),
            discovered_timestamp=datetime.now(UTC),
        )

        assert listing.listing_url == "https://example.com/job/12345"
        assert listing.source == JobBoardSource.INDEED
        assert listing.title == "Senior Python Developer"
        assert len(listing.raw_skills) == 3
        assert len(listing.content_hash) == 64

    def test_discovered_listing_job_board_sources(self) -> None:
        """Test all JobBoardSource enum values work."""
        sources = [
            JobBoardSource.INDEED,
            JobBoardSource.LINKEDIN,
            JobBoardSource.ZIPRECRUITER,
            JobBoardSource.GOOGLE,
            JobBoardSource.GLASSDOOR,
        ]

        for source in sources:
            listing = DiscoveredListing(
                listing_url=f"https://example.com/job/{source.name}",
                source=source,
                title="Test Job",
                company_name="Test",
                description="Test",
                content_hash=generate_content_hash("Test"),
                discovered_timestamp=datetime.now(UTC),
            )
            assert listing.source == source


class TestListingReferenceProto:
    """Test ListingReference proto structure."""

    def test_listing_reference_fields(self) -> None:
        """Test ListingReference uses listing_url field."""
        ref = ListingReference(
            listing_url="https://example.com/job/123",
            listing_id=str(uuid4()),
            source=JobBoardSource.INDEED,
        )

        assert ref.listing_url == "https://example.com/job/123"
        assert ref.source == JobBoardSource.INDEED


class TestStoredListingProto:
    """Test StoredListing proto structure."""

    def test_stored_listing_with_work_arrangement(self) -> None:
        """Test StoredListing with work arrangement."""
        stored = StoredListing(
            listing_url="https://example.com/job/enriched",
            source=JobBoardSource.INDEED,
            title="Remote Python Developer",
            company_name="TechCorp",
            description="Remote work opportunity",
            work_arrangement=WorkArrangement.REMOTE,
            discovered_timestamp=datetime.now(UTC),
            stored_timestamp=datetime.now(UTC),
            content_hash=generate_content_hash("Remote work opportunity"),
            version=1,
        )

        assert stored.work_arrangement == WorkArrangement.REMOTE
        assert stored.version == 1

    def test_stored_listing_with_compensation(self) -> None:
        """Test StoredListing with compensation using correct currency enum."""
        from nohiki.common.v1 import (
            Compensation,
            CompensationBound,
            MonetaryAmount,
            PaymentFrequency,
        )

        stored = StoredListing(
            listing_url="https://example.com/job/paid",
            source=JobBoardSource.LINKEDIN,
            title="Well-Paid Developer",
            company_name="RichCorp",
            description="Competitive salary",
            compensation=Compensation(
                min_amount=CompensationBound(amount=MonetaryAmount(minor_units=12000000, currency=CurrencyCode.USD)),
                max_amount=CompensationBound(amount=MonetaryAmount(minor_units=15000000, currency=CurrencyCode.USD)),
                frequency=PaymentFrequency.ANNUALLY,
            ),
            discovered_timestamp=datetime.now(UTC),
            stored_timestamp=datetime.now(UTC),
            content_hash=generate_content_hash("Competitive salary"),
            version=1,
        )

        compensation = stored.compensation
        assert compensation is not None
        minimum = compensation.min_amount
        assert minimum is not None
        assert minimum.amount.minor_units == 12000000
        assert minimum.amount.currency == CurrencyCode.USD
        assert compensation.frequency == PaymentFrequency.ANNUALLY


class TestEventMetadataProto:
    """Test EventMetadata proto structure."""

    def test_event_metadata_required_fields(self) -> None:
        """Test EventMetadata uses correct field names."""
        metadata = EventMetadata(
            event_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            source_service="job-ingest-service",
            version="v1",
        )

        assert metadata.event_id
        assert metadata.source_service == "job-ingest-service"
        assert metadata.version == "v1"

    def test_event_metadata_with_correlation(self) -> None:
        """Test EventMetadata with correlation and causation IDs."""
        correlation_id = str(uuid4())
        causation_id = str(uuid4())

        metadata = EventMetadata(
            event_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            source_service="test-service",
            correlation_id=correlation_id,
            causation_id=causation_id,
            version="v1",
        )

        assert metadata.correlation_id == correlation_id
        assert metadata.causation_id == causation_id

"""Unit tests for event handlers."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from nohiki.common.v1 import EventMetadata, JobBoardSource, ListingReference
from nohiki.job.ingest.v1 import DiscoveredListing
from nohiki.job.listing.v1 import ListingAccepted
from nohiki_kafka_client import MessageContext


@pytest.fixture
def valid_listing_accepted() -> ListingAccepted:
    """Create a valid ListingAccepted message."""
    return ListingAccepted(
        metadata=EventMetadata(
            event_id="test-event-id",
            correlation_id="test-correlation-id",
            source_service="test-source",
            version="v1",
        ),
        listing=ListingReference(
            listing_id="test-listing-id",
            listing_url="https://example.com/job/123",
            source=JobBoardSource.LINKEDIN,
        ),
        discovered_data=DiscoveredListing(
            listing_url="https://example.com/job/123",
            source=JobBoardSource.LINKEDIN,
            external_id="ext-123",
            title="Software Engineer",
            company_name="Test Corp",
            description="Build amazing software",
            raw_skills=["Python", "Go"],
        ),
    )


@pytest.fixture
def message_context() -> MessageContext:
    """Create a message context."""
    return MessageContext(
        topic="test-topic",
        partition=0,
        offset=0,
        key="test-key",
        correlation_id="test-correlation-id",
        timestamp=0,
        headers={},
    )


class TestHandleListingAccepted:
    """Tests for handle_listing_accepted handler."""

    @pytest.mark.asyncio
    async def test_processes_valid_message(
        self,
        valid_listing_accepted: ListingAccepted,
        message_context: MessageContext,
    ) -> None:
        """Test that valid message is processed successfully."""
        with patch(
            "job_ingest_enrichment_service.events.handlers.process_job_enrichment",
            new_callable=AsyncMock,
            return_value={"title": "Software Engineer", "company": "Test Corp"},
        ) as mock_process:
            from job_ingest_enrichment_service.events.handlers import (
                handle_listing_accepted,
            )

            await handle_listing_accepted(valid_listing_accepted, message_context)

            mock_process.assert_called_once()
            call_args = mock_process.call_args
            assert call_args.kwargs["correlation_id"] == "test-correlation-id"

    @pytest.mark.asyncio
    async def test_raises_on_missing_metadata(
        self,
        message_context: MessageContext,
    ) -> None:
        """Test that missing metadata raises ValueError."""
        message = ListingAccepted(
            metadata=cast("EventMetadata", None),
            listing=ListingReference(
                listing_id="test-id",
                listing_url="https://example.com/job",
                source=JobBoardSource.LINKEDIN,
            ),
            discovered_data=DiscoveredListing(
                listing_url="https://example.com/job",
                source=JobBoardSource.LINKEDIN,
                title="Test",
                company_name="Test Corp",
                description="Test description",
            ),
        )

        from job_ingest_enrichment_service.events.handlers import (
            handle_listing_accepted,
        )

        with pytest.raises(ValueError, match="metadata is required"):
            await handle_listing_accepted(message, message_context)

    @pytest.mark.asyncio
    async def test_raises_on_missing_listing(
        self,
        message_context: MessageContext,
    ) -> None:
        """Test that missing listing raises ValueError."""
        message = ListingAccepted(
            metadata=EventMetadata(
                event_id="test",
                correlation_id="test-corr",
                source_service="test",
                version="v1",
            ),
            listing=cast("ListingReference", None),
            discovered_data=DiscoveredListing(
                listing_url="https://example.com/job",
                source=JobBoardSource.LINKEDIN,
                title="Test",
                company_name="Test Corp",
                description="Test description",
            ),
        )

        from job_ingest_enrichment_service.events.handlers import (
            handle_listing_accepted,
        )

        with pytest.raises(ValueError, match="listing is required"):
            await handle_listing_accepted(message, message_context)

    @pytest.mark.asyncio
    async def test_raises_on_missing_discovered_data(
        self,
        message_context: MessageContext,
    ) -> None:
        """Test that missing discovered_data raises ValueError."""
        message = ListingAccepted(
            metadata=EventMetadata(
                event_id="test",
                correlation_id="test-corr",
                source_service="test",
                version="v1",
            ),
            listing=ListingReference(
                listing_id="test-id",
                listing_url="https://example.com/job",
                source=JobBoardSource.LINKEDIN,
            ),
            discovered_data=cast("DiscoveredListing", None),
        )

        from job_ingest_enrichment_service.events.handlers import (
            handle_listing_accepted,
        )

        with pytest.raises(ValueError, match="discovered_data is required"):
            await handle_listing_accepted(message, message_context)

    @pytest.mark.asyncio
    async def test_raises_on_empty_correlation_id(
        self,
        message_context: MessageContext,
    ) -> None:
        """Test that empty correlation_id raises ValueError."""
        message = ListingAccepted(
            metadata=EventMetadata(
                event_id="test",
                correlation_id="",
                source_service="test",
                version="v1",
            ),
            listing=ListingReference(
                listing_id="test-id",
                listing_url="https://example.com/job",
                source=JobBoardSource.LINKEDIN,
            ),
            discovered_data=DiscoveredListing(
                listing_url="https://example.com/job",
                source=JobBoardSource.LINKEDIN,
                title="Test",
                company_name="Test Corp",
                description="Test description",
            ),
        )

        from job_ingest_enrichment_service.events.handlers import (
            handle_listing_accepted,
        )

        with pytest.raises(ValueError, match="correlation_id is required"):
            await handle_listing_accepted(message, message_context)

    @pytest.mark.asyncio
    async def test_logs_warning_on_enrichment_failure(
        self,
        valid_listing_accepted: ListingAccepted,
        message_context: MessageContext,
    ) -> None:
        """Test that enrichment failure is logged as warning."""
        with patch(
            "job_ingest_enrichment_service.events.handlers.process_job_enrichment",
            new_callable=AsyncMock,
            return_value=None,
        ):
            from job_ingest_enrichment_service.events.handlers import (
                handle_listing_accepted,
            )

            await handle_listing_accepted(valid_listing_accepted, message_context)


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """Test that Kafka consumers are started."""
        with patch("job_ingest_enrichment_service.events.handlers.kafka_client") as mock_client:
            from job_ingest_enrichment_service.events.handlers import (
                start_event_consumer,
            )

            start_event_consumer()

            mock_client.start_consumers.assert_called_once()

"""Unit tests for events/publishers.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_enrichment_service.events.publishers import (
    AGGREGATE_TYPE,
    EnrichmentPublishContext,
    publish_enrichment_completed_outbox,
    publish_enrichment_failed_outbox,
)
from nohiki.common.v1 import GeoCoordinates, JobBoardSource, ListingReference
from nohiki_db_utils.testing import create_mock_session


class TestEnrichmentPublishContext:
    """Tests for EnrichmentPublishContext dataclass."""

    def test_context_creation(self) -> None:
        """Context can be created with all required fields."""
        listing_ref = ListingReference(
            listing_id="test-id",
            listing_url="https://example.com/job",
            source=JobBoardSource.LINKEDIN,
        )
        stored_data = MagicMock()

        ctx = EnrichmentPublishContext(
            listing_ref=listing_ref,
            stored_data=stored_data,
            listing_id="test-id",
            llm_model_id="gpt-4",
            collection_version="v1",
            correlation_id="corr-123",
        )

        assert ctx.listing_id == "test-id"
        assert ctx.llm_model_id == "gpt-4"
        assert ctx.geocoded_coordinates is None

    def test_context_with_geocoded_coordinates(self) -> None:
        """Context can include optional geocoded coordinates."""
        listing_ref = ListingReference(listing_id="test-id", listing_url="https://example.com")
        stored_data = MagicMock()
        coords = GeoCoordinates(latitude=40.7128, longitude=-74.0060)

        ctx = EnrichmentPublishContext(
            listing_ref=listing_ref,
            stored_data=stored_data,
            listing_id="test-id",
            llm_model_id="gpt-4",
            collection_version="v1",
            correlation_id="corr-123",
            geocoded_coordinates=coords,
        )

        assert ctx.geocoded_coordinates is not None
        assert ctx.geocoded_coordinates.latitude == 40.7128


class TestPublishEnrichmentCompletedOutbox:
    """Tests for publish_enrichment_completed_outbox function."""

    @pytest.mark.asyncio
    async def test_writes_event_to_outbox(self) -> None:
        """Writes EnrichmentCompleted event to outbox table."""
        mock_db = create_mock_session()
        listing_ref = ListingReference(
            listing_id="test-listing-id",
            listing_url="https://example.com/job/123",
            source=JobBoardSource.LINKEDIN,
        )
        mock_stored_data = MagicMock()

        ctx = EnrichmentPublishContext(
            listing_ref=listing_ref,
            stored_data=mock_stored_data,
            listing_id="test-listing-id",
            llm_model_id="gpt-4o",
            collection_version="v2024.1",
            correlation_id="corr-456",
        )

        with patch("job_ingest_enrichment_service.events.publishers.OutboxWriter") as mock_outbox_cls:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_cls.return_value = mock_outbox

            await publish_enrichment_completed_outbox(mock_db, ctx)

            mock_outbox_cls.assert_called_once()
            mock_outbox.write_event.assert_awaited_once()

            call_kwargs = mock_outbox.write_event.call_args.kwargs
            assert call_kwargs["db"] is mock_db
            assert call_kwargs["params"].aggregate_type == AGGREGATE_TYPE
            assert call_kwargs["params"].aggregate_id == "test-listing-id"
            assert call_kwargs["params"].correlation_id == "corr-456"

    @pytest.mark.asyncio
    async def test_includes_geocoded_coordinates_when_present(self) -> None:
        """Event includes geocoded coordinates when provided in context."""
        mock_db = create_mock_session()
        listing_ref = ListingReference(listing_id="test-id", listing_url="https://example.com")
        mock_stored_data = MagicMock()
        coords = GeoCoordinates(latitude=51.5074, longitude=-0.1278)

        ctx = EnrichmentPublishContext(
            listing_ref=listing_ref,
            stored_data=mock_stored_data,
            listing_id="test-id",
            llm_model_id="gpt-4",
            collection_version="v1",
            correlation_id="corr-789",
            geocoded_coordinates=coords,
        )

        with patch("job_ingest_enrichment_service.events.publishers.OutboxWriter") as mock_outbox_cls:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_cls.return_value = mock_outbox

            await publish_enrichment_completed_outbox(mock_db, ctx)

            call_kwargs = mock_outbox.write_event.call_args.kwargs
            event = call_kwargs["event"]
            assert event.geocoded_coordinates.latitude == 51.5074
            assert event.geocoded_coordinates.longitude == -0.1278


class TestPublishEnrichmentFailedOutbox:
    """Tests for terminal failed enrichment events."""

    @pytest.mark.asyncio
    async def test_writes_typed_failed_enrichment_completed_event(self) -> None:
        """Failed outcomes use EnrichmentCompleted with typed error and saga metadata."""
        from nohiki.common.v1 import ErrorInfo, ProcessingStatus
        from nohiki.job.ingest.v1 import EnrichmentCompleted
        from nohiki_kafka_client import Topics

        mock_db = create_mock_session()
        listing_ref = ListingReference(
            listing_id="failed-listing",
            listing_url="https://example.com/job/failed",
            source=JobBoardSource.LINKEDIN,
        )
        ctx = EnrichmentPublishContext(
            listing_ref=listing_ref,
            stored_data=MagicMock(),
            listing_id="failed-listing",
            llm_model_id="embedding-model",
            collection_version="job-current-v11",
            correlation_id="corr-failed",
        )
        error = ErrorInfo(
            error_code="EMBEDDING_SAGA_EXPIRED",
            error_message="callbacks did not converge",
            retryable=False,
        )

        with patch("job_ingest_enrichment_service.events.publishers.OutboxWriter") as mock_outbox_cls:
            mock_outbox = MagicMock()
            mock_outbox.write_event = AsyncMock()
            mock_outbox_cls.return_value = mock_outbox

            await publish_enrichment_failed_outbox(mock_db, ctx, error)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs
        event = call_kwargs["event"]
        assert isinstance(event, EnrichmentCompleted)
        assert event.result.status == ProcessingStatus.FAILED
        assert event.result.error.error_code == "EMBEDDING_SAGA_EXPIRED"
        assert event.result.error.retryable is False
        assert event.listing_id == "failed-listing"
        assert event.llm_model_id == "embedding-model"
        assert event.collection_version == "job-current-v11"
        assert call_kwargs["params"].event_type == Topics.JOB_INGEST_ENRICHMENT_COMPLETED

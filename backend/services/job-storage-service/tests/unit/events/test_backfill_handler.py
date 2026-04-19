"""Unit tests for backfill_handler module."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import CommandHeader, JobBoardSource, ListingStatus, WorkArrangement
from nohiki.job.listing.v1 import BackfillRequested
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


@pytest.fixture
def mock_message_context() -> MessageContext:
    """Create mock message context with injected db_session."""
    return MessageContext(
        topic="test-topic",
        partition=0,
        offset=0,
        timestamp=1704067200000,
        headers={},
        key=None,
        correlation_id=str(uuid4()),
        retry_count=0,
        db_session=create_mock_session(),
    )


@pytest.fixture
def sample_backfill_request() -> BackfillRequested:
    """Create a sample BackfillRequested message."""
    from nohiki.job.listing.v1 import BackfillRequested

    return BackfillRequested(
        command=CommandHeader(
            operation_id=str(uuid4()),
            callback_topic="job-correlation.sys.backfill-listings.v1",
        ),
        pref_id=str(uuid4()),
        user_id=str(uuid4()),
        max_listings=100,
        since_days=14,
    )


@pytest.fixture
def sample_listing_mock() -> MagicMock:
    """Create a sample listing mock for testing."""
    listing = MagicMock()
    listing.id = uuid4()
    listing.listing_url = "https://example.com/job/123"
    listing.job_board_source = JobBoardSource.LINKEDIN
    listing.title = "Software Engineer"
    listing.company_name = "Tech Corp"
    listing.description = "Build amazing software"
    listing.location = {"city": "San Francisco", "state": "CA", "country": "USA"}
    listing.work_arrangement = WorkArrangement.HYBRID
    listing.status = ListingStatus.ACTIVE
    listing.discovered_at = datetime.now(UTC)
    listing.processed_at = datetime.now(UTC)
    listing.version = 1
    listing.raw_content_hash = "abc123"
    listing.required_skills = ["Python", "FastAPI"]
    listing.min_experience_years = 2
    listing.max_experience_years = 5
    listing.compensation = None
    listing.seniority_level = None
    listing.posted_at = None
    listing.created_at = datetime.now(UTC)
    listing.updated_at = datetime.now(UTC)
    return listing


class TestHandleBackfillRequested:
    """Tests for handle_backfill_requested handler."""

    @pytest.mark.asyncio
    async def test_publishes_listings(
        self,
        sample_backfill_request: MagicMock,
        mock_message_context: MessageContext,
        sample_listing_mock: MagicMock,
    ) -> None:
        """Test that handler publishes listings when found."""
        with (
            patch("job_storage_service.events.backfill_handler.JobStoreService") as mock_service_class,
            patch("job_storage_service.events.backfill_handler.kafka_client") as mock_get_kafka,
            patch("job_storage_service.events.backfill_handler.build_listing_snapshot") as mock_build_snapshot,
        ):
            mock_service = AsyncMock()
            mock_service.get_listings_for_backfill.return_value = [sample_listing_mock]
            mock_service_class.return_value = mock_service

            mock_snapshot = MagicMock()
            mock_build_snapshot.return_value = mock_snapshot

            mock_get_kafka.publish = AsyncMock()

            from job_storage_service.events.backfill_handler import (
                handle_backfill_requested,
            )

            await handle_backfill_requested(sample_backfill_request, mock_message_context)

            mock_service.get_listings_for_backfill.assert_called_once()
            mock_get_kafka.publish.assert_called()

    @pytest.mark.asyncio
    async def test_respects_batch_size(
        self,
        sample_backfill_request: MagicMock,
        mock_message_context: MessageContext,
        sample_listing_mock: MagicMock,
    ) -> None:
        """Test that handler respects batch_size configuration."""
        listings = [MagicMock() for _ in range(75)]
        for i, listing in enumerate(listings):
            listing.id = uuid4()
            listing.listing_url = f"https://example.com/job/{i}"
            listing.job_board_source = JobBoardSource.LINKEDIN
            listing.title = f"Job {i}"
            listing.company_name = "Tech Corp"
            listing.description = "Build amazing software"
            listing.location = {"city": "San Francisco", "country": "USA"}
            listing.work_arrangement = WorkArrangement.HYBRID
            listing.status = ListingStatus.ACTIVE
            listing.discovered_at = datetime.now(UTC)
            listing.processed_at = datetime.now(UTC)
            listing.version = 1
            listing.raw_content_hash = "abc123"
            listing.required_skills = []
            listing.min_experience_years = None
            listing.max_experience_years = None
            listing.compensation = None
            listing.seniority_level = None
            listing.posted_at = None
            listing.created_at = datetime.now(UTC)
            listing.updated_at = datetime.now(UTC)

        with (
            patch("job_storage_service.events.backfill_handler.settings") as mock_settings,
            patch("job_storage_service.events.backfill_handler.JobStoreService") as mock_service_class,
            patch("job_storage_service.events.backfill_handler.kafka_client") as mock_get_kafka,
            patch("job_storage_service.events.backfill_handler.build_listing_snapshot") as mock_build_snapshot,
        ):
            mock_settings.backfill.default_max_listings = 500
            mock_settings.backfill.default_since_days = 30
            mock_settings.backfill.batch_size = 50
            mock_settings.service_name = "job-storage-service"

            mock_service = AsyncMock()
            mock_service.get_listings_for_backfill.return_value = listings
            mock_service_class.return_value = mock_service

            mock_snapshot = MagicMock()
            mock_build_snapshot.return_value = mock_snapshot

            mock_get_kafka.publish = AsyncMock()

            from job_storage_service.events.backfill_handler import (
                handle_backfill_requested,
            )

            await handle_backfill_requested(sample_backfill_request, mock_message_context)

            assert mock_get_kafka.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_result_publishes_empty_response(
        self,
        sample_backfill_request: MagicMock,
        mock_message_context: MessageContext,
    ) -> None:
        """Test that empty listings result publishes empty response."""
        with (
            patch("job_storage_service.events.backfill_handler.JobStoreService") as mock_service_class,
            patch("job_storage_service.events.backfill_handler.kafka_client") as mock_get_kafka,
        ):
            mock_service = AsyncMock()
            mock_service.get_listings_for_backfill.return_value = []
            mock_service_class.return_value = mock_service

            mock_get_kafka.publish = AsyncMock()

            from job_storage_service.events.backfill_handler import (
                handle_backfill_requested,
            )

            await handle_backfill_requested(sample_backfill_request, mock_message_context)

            mock_get_kafka.publish.assert_called_once()
            call_args = mock_get_kafka.publish.call_args
            published_event = call_args[0][1]
            assert published_event.success.total_listings == 0
            assert published_event.success.is_final_batch is True

    @pytest.mark.asyncio
    async def test_sets_correct_batch_metadata(
        self,
        sample_backfill_request: MagicMock,
        mock_message_context: MessageContext,
        sample_listing_mock: MagicMock,
    ) -> None:
        """Test that batch metadata is set correctly."""
        with (
            patch("job_storage_service.events.backfill_handler.settings") as mock_settings,
            patch("job_storage_service.events.backfill_handler.JobStoreService") as mock_service_class,
            patch("job_storage_service.events.backfill_handler.kafka_client") as mock_get_kafka,
            patch("job_storage_service.events.backfill_handler.build_listing_snapshot") as mock_build_snapshot,
        ):
            mock_settings.backfill.default_max_listings = 500
            mock_settings.backfill.default_since_days = 30
            mock_settings.backfill.batch_size = 50
            mock_settings.service_name = "job-storage-service"

            mock_service = AsyncMock()
            mock_service.get_listings_for_backfill.return_value = [sample_listing_mock]
            mock_service_class.return_value = mock_service

            mock_snapshot = MagicMock()
            mock_build_snapshot.return_value = mock_snapshot

            mock_get_kafka.publish = AsyncMock()

            from job_storage_service.events.backfill_handler import (
                handle_backfill_requested,
            )

            await handle_backfill_requested(sample_backfill_request, mock_message_context)

            call_args = mock_get_kafka.publish.call_args
            published_event = call_args[0][1]
            assert published_event.success.batch_number == 1
            assert published_event.success.total_batches == 1
            assert published_event.success.is_final_batch is True
            assert published_event.success.total_listings == 1

    @pytest.mark.asyncio
    async def test_uses_config_defaults(
        self,
        mock_message_context: MessageContext,
    ) -> None:
        """Test that handler uses config defaults when message values are 0."""
        from nohiki.job.listing.v1 import BackfillRequested

        request = BackfillRequested(
            command=CommandHeader(
                operation_id=str(uuid4()),
                callback_topic="job-correlation.sys.backfill-listings.v1",
            ),
            pref_id=str(uuid4()),
            user_id=str(uuid4()),
            max_listings=0,
            since_days=0,
        )

        with (
            patch("job_storage_service.events.backfill_handler.settings") as mock_settings,
            patch("job_storage_service.events.backfill_handler.JobStoreService") as mock_service_class,
            patch("job_storage_service.events.backfill_handler.kafka_client") as mock_get_kafka,
        ):
            mock_settings.backfill.default_max_listings = 500
            mock_settings.backfill.default_since_days = 30
            mock_settings.backfill.batch_size = 50
            mock_settings.service_name = "job-storage-service"

            mock_service = AsyncMock()
            mock_service.get_listings_for_backfill.return_value = []
            mock_service_class.return_value = mock_service

            mock_get_kafka.publish = AsyncMock()

            from job_storage_service.events.backfill_handler import (
                handle_backfill_requested,
            )

            await handle_backfill_requested(request, mock_message_context)

            call_args = mock_service.get_listings_for_backfill.call_args
            assert call_args.kwargs["max_listings"] == 500
            assert call_args.kwargs["since_days"] == 30

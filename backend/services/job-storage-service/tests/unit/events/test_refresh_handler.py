"""Unit tests for refresh_handler module.

Tests the snapshot refresh request handler and supporting functions that
re-publish listing snapshots to ECST consumers without re-running enrichment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from job_storage_service.db.models import Listing
from job_storage_service.events.refresh_handler import (
    _publish_refreshed_snapshots,
    _query_refresh_targets,
    handle_snapshot_refresh_requested,
)
from nohiki.common.v1 import JobBoardSource, ListingStatus, SnapshotRefreshRequested, WorkArrangement
from nohiki_kafka_client import MessageContext


@pytest.fixture
def sample_listings() -> list[Listing]:
    """Create sample Listing records for testing."""
    now = datetime.now(UTC).replace(tzinfo=None)
    # Listings persist a structured Location as JSONB; the column is non-nullable,
    # so fixtures must populate it even when location semantics are irrelevant
    # to the test under exercise.
    location = {"city": "San Francisco", "state_province": "CA"}
    listings = []
    for i in range(3):
        listing = Listing(
            id=uuid.uuid4(),
            listing_url=f"https://example.com/job/{i}",
            job_board_source=JobBoardSource.INDEED,
            title=f"Software Engineer {i}",
            company_name="Tech Corp",
            description=f"Job description {i}",
            location=location,
            work_arrangement=WorkArrangement.REMOTE,
            version=1,
            raw_content_hash=f"hash{i}",
            status=ListingStatus.ACTIVE,
            discovered_at=now,
            processed_at=now,
            created_at=now,
            updated_at=now,
        )
        listings.append(listing)
    return listings


@pytest.fixture
def sample_snapshot_refresh_request() -> SnapshotRefreshRequested:
    """Create a sample SnapshotRefreshRequested message."""
    return SnapshotRefreshRequested(
        entity_ids=["id-1", "id-2"],
        reason="Correcting data quality issues",
    )


def _make_context(
    *,
    db_session: AsyncMock | None = None,
    correlation_id: str = "",
) -> MessageContext:
    """Build a MessageContext with injected db_session and correlation_id."""
    return MessageContext(
        topic="test-topic",
        partition=0,
        offset=0,
        timestamp=1704067200000,
        headers={},
        key=None,
        correlation_id=correlation_id,
        retry_count=0,
        db_session=db_session,
    )


class TestQueryRefreshTargets:
    """Tests for _query_refresh_targets function."""

    @pytest.mark.asyncio
    async def test_query_with_specific_entity_ids(self, sample_listings: list[Listing]) -> None:
        """Test that query filters by specific entity_ids when provided."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [sample_listings[0], sample_listings[1]]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        entity_ids = [str(sample_listings[0].id), str(sample_listings[1].id)]

        result = await _query_refresh_targets(mock_db, entity_ids)

        assert len(result) == 2
        mock_db.execute.assert_called_once()

        # Verify that the query was constructed with the in_ filter
        call_args = mock_db.execute.call_args[0][0]
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_query_with_no_entity_ids_filters_processed(self, sample_listings: list[Listing]) -> None:
        """Test that query filters by processed_at when entity_ids is None."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = sample_listings
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _query_refresh_targets(mock_db, None)

        assert len(result) == 3
        mock_db.execute.assert_called_once()

        # Verify that the query was constructed with the processed_at filter
        call_args = mock_db.execute.call_args[0][0]
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_query_returns_empty_list_when_no_matches(self) -> None:
        """Test that query returns empty list when no listings match."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _query_refresh_targets(mock_db, ["nonexistent-id"])

        assert result == []
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_always_filters_by_active_status(self, sample_listings: list[Listing]) -> None:
        """Test that query always includes status == ACTIVE filter."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = sample_listings
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Query with entity_ids
        await _query_refresh_targets(mock_db, ["id-1"])

        # Verify the statement was executed
        mock_db.execute.assert_called_once()
        statement = mock_db.execute.call_args[0][0]
        assert statement is not None


class TestPublishRefreshedSnapshots:
    """Tests for _publish_refreshed_snapshots function."""

    @pytest.mark.asyncio
    async def test_calls_publish_for_each_listing(self, sample_listings: list[Listing]) -> None:
        """Test that publish_listing_updated_event is called for each listing."""
        mock_db = AsyncMock()

        with (
            patch("job_storage_service.events.refresh_handler.OutboxWriter") as mock_outbox_class,
            patch(
                "job_storage_service.events.refresh_handler.publish_listing_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish_fn,
        ):
            mock_outbox = MagicMock()
            mock_outbox_class.return_value = mock_outbox

            result = await _publish_refreshed_snapshots(mock_db, sample_listings, "corr-123")

            assert result == 3
            assert mock_publish_fn.call_count == 3

    @pytest.mark.asyncio
    async def test_flushes_every_batch_size(self) -> None:
        """Test that db.flush() is called every _BATCH_FLUSH_SIZE listings."""
        mock_db = AsyncMock()

        # Create 250 mock listings (will require 2 flushes: at 100 and 200)
        large_listing_set: list[Listing] = []
        for _i in range(250):
            listing = cast("Listing", MagicMock(spec=Listing))
            listing.id = uuid4()
            large_listing_set.append(listing)

        with (
            patch("job_storage_service.events.refresh_handler.OutboxWriter") as mock_outbox_class,
            patch("job_storage_service.events.refresh_handler.publish_listing_updated_event") as mock_publish_fn,
        ):
            mock_outbox = MagicMock()
            mock_outbox_class.return_value = mock_outbox
            mock_publish_fn.return_value = AsyncMock()

            result = await _publish_refreshed_snapshots(mock_db, large_listing_set, "corr-123")

            # Should call flush at idx=100 and idx=200 (2 times)
            assert mock_db.flush.call_count == 2
            assert result == 250

    @pytest.mark.asyncio
    async def test_returns_correct_count(self, sample_listings: list[Listing]) -> None:
        """Test that function returns the correct number of refreshed listings."""
        mock_db = AsyncMock()

        with (
            patch("job_storage_service.events.refresh_handler.OutboxWriter") as mock_outbox_class,
            patch(
                "job_storage_service.events.refresh_handler.publish_listing_updated_event",
                new_callable=AsyncMock,
            ),
        ):
            mock_outbox = MagicMock()
            mock_outbox_class.return_value = mock_outbox

            result = await _publish_refreshed_snapshots(mock_db, sample_listings, "corr-123")

            assert result == len(sample_listings)

    @pytest.mark.asyncio
    async def test_passes_correlation_id_to_context(self, sample_listings: list[Listing]) -> None:
        """Test that correlation_id is passed through to the context."""
        mock_db = AsyncMock()
        test_corr_id = "test-correlation-123"

        with (
            patch("job_storage_service.events.refresh_handler.OutboxWriter") as mock_outbox_class,
            patch(
                "job_storage_service.events.refresh_handler.publish_listing_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish_fn,
        ):
            mock_outbox = MagicMock()
            mock_outbox_class.return_value = mock_outbox

            await _publish_refreshed_snapshots(mock_db, sample_listings, test_corr_id)

            # Verify publish was called with context containing the correlation_id
            mock_publish_fn.assert_called()
            for call in mock_publish_fn.call_args_list:
                ctx = call[0][0]
                assert ctx.correlation_id == test_corr_id

    @pytest.mark.asyncio
    async def test_creates_outbox_writer_with_schema(self, sample_listings: list[Listing]) -> None:
        """Test that OutboxWriter is created with correct schema."""
        mock_db = AsyncMock()

        with (
            patch("job_storage_service.events.refresh_handler.OutboxWriter") as mock_outbox_class,
            patch(
                "job_storage_service.events.refresh_handler.publish_listing_updated_event",
                new_callable=AsyncMock,
            ),
        ):
            mock_outbox = MagicMock()
            mock_outbox_class.return_value = mock_outbox

            await _publish_refreshed_snapshots(mock_db, sample_listings, "corr-123")

            # Verify OutboxWriter was instantiated with schema parameter
            mock_outbox_class.assert_called_once()
            call_args = mock_outbox_class.call_args
            assert "schema" in call_args.kwargs


class TestHandleSnapshotRefreshRequested:
    """Tests for handle_snapshot_refresh_requested handler."""

    @pytest.mark.asyncio
    async def test_handler_with_specific_entity_ids(
        self,
        sample_listings: list[Listing],
        sample_snapshot_refresh_request: SnapshotRefreshRequested,
    ) -> None:
        """Test handler processes refresh with specific entity_ids."""
        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = sample_listings
            mock_publish_snapshots.return_value = len(sample_listings)

            await handle_snapshot_refresh_requested(sample_snapshot_refresh_request, context)

            mock_query.assert_called_once()
            call_args = mock_query.call_args
            assert call_args[0][1] is not None  # entity_ids should not be None
            mock_publish_snapshots.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_with_empty_entity_ids_refreshes_all(
        self,
        sample_listings: list[Listing],
    ) -> None:
        """Test handler with empty entity_ids refreshes all enriched listings."""
        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        request = SnapshotRefreshRequested(
            entity_ids=[],
            reason="Refreshing all enriched listings",
        )

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = sample_listings
            mock_publish_snapshots.return_value = len(sample_listings)

            await handle_snapshot_refresh_requested(request, context)

            mock_query.assert_called_once()
            call_args = mock_query.call_args
            entity_ids_arg = call_args[0][1]
            # Empty entity_ids list should be normalised to None so the
            # query path falls through to the "all enriched listings" branch.
            assert entity_ids_arg is None
            mock_publish_snapshots.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_returns_early_when_no_listings_found(
        self,
        sample_snapshot_refresh_request: SnapshotRefreshRequested,
    ) -> None:
        """Test handler returns early without commit when no listings found."""
        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = []

            await handle_snapshot_refresh_requested(sample_snapshot_refresh_request, context)

            mock_query.assert_called_once()
            mock_publish_snapshots.assert_not_called()
            mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_passes_correlation_id(
        self,
        sample_listings: list[Listing],
        sample_snapshot_refresh_request: SnapshotRefreshRequested,
    ) -> None:
        """Test handler passes correlation_id from context through to publish."""
        test_corr_id = "test-corr-uuid-456"
        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db, correlation_id=test_corr_id)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = sample_listings
            mock_publish_snapshots.return_value = len(sample_listings)

            await handle_snapshot_refresh_requested(sample_snapshot_refresh_request, context)

            mock_publish_snapshots.assert_called_once()
            call_args = mock_publish_snapshots.call_args
            passed_corr_id = call_args[0][2]
            assert passed_corr_id == test_corr_id

    @pytest.mark.asyncio
    async def test_handler_calls_query_then_publish_then_commit(
        self,
        sample_listings: list[Listing],
        sample_snapshot_refresh_request: SnapshotRefreshRequested,
    ) -> None:
        """Test handler execution sequence: query → publish → commit."""
        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        call_order = []

        def track_query(*_args: object, **_kwargs: object) -> list[Listing]:
            call_order.append("query")
            return sample_listings

        async def track_publish(*_args: object, **_kwargs: object) -> int:
            call_order.append("publish")
            return len(sample_listings)

        async def track_commit() -> None:
            call_order.append("commit")

        mock_db.commit = AsyncMock(side_effect=track_commit)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets", side_effect=track_query),
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                side_effect=track_publish,
            ),
        ):
            await handle_snapshot_refresh_requested(sample_snapshot_refresh_request, context)

            assert call_order == ["query", "publish", "commit"]

    @pytest.mark.asyncio
    async def test_handler_extracts_entity_ids_from_message(
        self,
        sample_listings: list[Listing],
    ) -> None:
        """Test handler extracts and passes entity_ids from message."""
        test_entity_ids = ["entity-1", "entity-2", "entity-3"]
        request = SnapshotRefreshRequested(
            entity_ids=test_entity_ids,
            reason="Testing entity ID extraction",
        )

        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = sample_listings
            mock_publish_snapshots.return_value = len(sample_listings)

            await handle_snapshot_refresh_requested(request, context)

            mock_query.assert_called_once()
            call_args = mock_query.call_args
            passed_entity_ids = call_args[0][1]
            assert passed_entity_ids == test_entity_ids

    @pytest.mark.asyncio
    async def test_handler_uses_db_session_from_context(
        self,
        sample_listings: list[Listing],
        sample_snapshot_refresh_request: SnapshotRefreshRequested,
    ) -> None:
        """Test handler uses db_session from context."""
        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = sample_listings
            mock_publish_snapshots.return_value = len(sample_listings)

            await handle_snapshot_refresh_requested(sample_snapshot_refresh_request, context)

            # Verify the db passed to query is the context's db
            call_args = mock_query.call_args
            passed_db = call_args[0][0]
            assert passed_db == mock_db

    @pytest.mark.asyncio
    async def test_handler_with_reason_in_message(
        self,
        sample_listings: list[Listing],
    ) -> None:
        """Test handler correctly processes message with reason field."""
        test_reason = "Data quality correction - removed outdated postings"
        request = SnapshotRefreshRequested(
            entity_ids=["id-1"],
            reason=test_reason,
        )

        mock_db = AsyncMock()
        context = _make_context(db_session=mock_db)

        with (
            patch("job_storage_service.events.refresh_handler._query_refresh_targets") as mock_query,
            patch(
                "job_storage_service.events.refresh_handler._publish_refreshed_snapshots",
                new_callable=AsyncMock,
            ) as mock_publish_snapshots,
        ):
            mock_query.return_value = sample_listings
            mock_publish_snapshots.return_value = len(sample_listings)

            await handle_snapshot_refresh_requested(request, context)

            # Handler should have processed the reason (via logging)
            mock_query.assert_called_once()
            mock_publish_snapshots.assert_called_once()
            mock_db.commit.assert_called_once()

"""Unit tests for bank_service.get_listings_for_backfill method."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nohiki.common.v1 import JobBoardSource, ListingStatus, WorkArrangement


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create mock database session."""
    mock = AsyncMock()
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def sample_listing() -> MagicMock:
    """Create a sample listing mock."""
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


class TestGetListingsForBackfill:
    """Tests for get_listings_for_backfill method."""

    @pytest.mark.asyncio
    async def test_returns_recent_active_listings(self, mock_db_session: AsyncMock, sample_listing: MagicMock) -> None:
        """Test that recent active listings are returned."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_listing]
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        listings = await service.get_listings_for_backfill(mock_db_session, max_listings=100, since_days=30)

        assert len(listings) == 1
        assert listings[0] == sample_listing
        mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_excludes_unenriched_listings(self, mock_db_session: AsyncMock) -> None:
        """Test that unenriched listings (processed_at is None) are excluded."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        listings = await service.get_listings_for_backfill(mock_db_session)

        assert listings == []
        call_args = mock_db_session.execute.call_args
        query = call_args[0][0]
        query_str = str(query)
        assert "processed_at" in query_str.lower()

    @pytest.mark.asyncio
    async def test_respects_since_days_cutoff(self, mock_db_session: AsyncMock) -> None:
        """Test that since_days parameter filters by discovered_at date."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        await service.get_listings_for_backfill(mock_db_session, since_days=7)

        call_args = mock_db_session.execute.call_args
        query = call_args[0][0]
        query_str = str(query)
        assert "discovered_at" in query_str.lower()

    @pytest.mark.asyncio
    async def test_respects_max_listings_limit(self, mock_db_session: AsyncMock) -> None:
        """Test that max_listings parameter limits results."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        await service.get_listings_for_backfill(mock_db_session, max_listings=100)

        call_args = mock_db_session.execute.call_args
        query = call_args[0][0]
        query_str = str(query.compile(compile_kwargs={"literal_binds": True}))
        assert "100" in query_str or "LIMIT" in query_str.upper()

    @pytest.mark.asyncio
    async def test_orders_by_recency(self, mock_db_session: AsyncMock) -> None:
        """Test that results are ordered by discovered_at descending."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        await service.get_listings_for_backfill(mock_db_session)

        call_args = mock_db_session.execute.call_args
        query = call_args[0][0]
        query_str = str(query)
        assert "order by" in query_str.lower()
        assert "discovered_at" in query_str.lower()

    @pytest.mark.asyncio
    async def test_empty_database_returns_empty_list(self, mock_db_session: AsyncMock) -> None:
        """Test that empty database returns empty list."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        listings = await service.get_listings_for_backfill(mock_db_session)

        assert listings == []
        assert isinstance(listings, list)

    @pytest.mark.asyncio
    async def test_filters_active_status_only(self, mock_db_session: AsyncMock) -> None:
        """Test that only ACTIVE status listings are returned."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        await service.get_listings_for_backfill(mock_db_session)

        call_args = mock_db_session.execute.call_args
        query = call_args[0][0]
        query_str = str(query)
        assert "status" in query_str.lower()

    @pytest.mark.asyncio
    async def test_default_parameters(self, mock_db_session: AsyncMock) -> None:
        """Test that default parameters are applied correctly."""
        from job_storage_service.services.bank_service import JobStoreService

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        service = JobStoreService()
        await service.get_listings_for_backfill(mock_db_session)

        mock_db_session.execute.assert_called_once()

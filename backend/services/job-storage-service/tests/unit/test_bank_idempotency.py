"""Idempotency tests for job-storage-service handlers.

Verifies that duplicate events are handled gracefully via IntegrityError
catching in the handler layer and content-hash dedup in the service layer.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from sqlalchemy.exc import IntegrityError


def _make_context(
    *,
    db_session: AsyncMock | None = None,
) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


class TestDiscoveredListingIdempotency:
    """Verify handle_job_raw_found catches IntegrityError on duplicates."""

    @pytest.mark.asyncio
    async def test_duplicate_discovered_listing_returns_silently(self) -> None:
        """Processing the same ListingDiscovered twice must not raise."""
        from job_storage_service.events.handlers import handle_job_raw_found

        listing = MagicMock()
        listing.listing_url = "https://example.com/job/1"

        metadata = MagicMock()
        metadata.correlation_id = "corr-1"

        message = MagicMock()
        message.listing = listing
        message.metadata = metadata
        message.discovered_at = MagicMock()
        message.discovered_data = MagicMock()
        message.query_id = "q-1"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch("job_storage_service.events.handlers.JobStoreService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc
            mock_svc.handle_discovered_listing.side_effect = IntegrityError(
                "duplicate", params=None, orig=Exception("unique violation")
            )

            await handle_job_raw_found(message, context)

    @pytest.mark.asyncio
    async def test_first_processing_succeeds(self) -> None:
        """First processing of a discovered listing succeeds normally."""
        import uuid

        from job_storage_service.events.handlers import handle_job_raw_found
        from job_storage_service.services.bank_service import _SagaIngestResult

        listing = MagicMock()
        listing.listing_url = "https://example.com/job/2"

        metadata = MagicMock()
        metadata.correlation_id = "corr-2"

        message = MagicMock()
        message.listing = listing
        message.metadata = metadata
        message.discovered_at = MagicMock()
        message.discovered_data = MagicMock()
        message.query_id = "q-2"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch("job_storage_service.events.handlers.JobStoreService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc
            mock_svc.handle_discovered_listing.return_value = _SagaIngestResult(saga_id=uuid.uuid4(), is_new=True)

            await handle_job_raw_found(message, context)

            mock_svc.handle_discovered_listing.assert_awaited_once()


class TestEnrichmentCompletedIdempotency:
    """Verify handle_job_processing_completed catches IntegrityError on duplicates."""

    @pytest.mark.asyncio
    async def test_duplicate_enrichment_returns_silently(self) -> None:
        """Processing the same EnrichmentCompleted twice must not raise."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        listing = MagicMock()
        listing.listing_url = "https://example.com/job/3"

        metadata = MagicMock()
        metadata.correlation_id = "corr-3"

        result = MagicMock()
        result.status = "COMPLETED"

        message = MagicMock()
        message.listing = listing
        message.metadata = metadata
        message.result = result
        message.stored_data = MagicMock()
        message.collection_version = "v1"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch("job_storage_service.events.handlers.JobStoreService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc_cls.return_value = mock_svc
            orig = MagicMock()
            orig.sqlstate = "23505"
            mock_svc.bank_stored_listing.side_effect = IntegrityError("duplicate", params=None, orig=orig)

            await handle_job_processing_completed(message, context)

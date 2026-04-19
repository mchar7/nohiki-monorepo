"""Saga ingestion behavior for handle_discovered_listing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_storage_service.services.bank_service import JobStoreService, RawJobContext
from nohiki.common.v1 import ListingReference
from nohiki.job.ingest.v1 import DiscoveredListing


def _mock_db() -> AsyncMock:
    """Build an AsyncMock session that does not auto-coroutine sync helpers."""
    mock = AsyncMock()
    mock.add = MagicMock()
    return mock


def _ctx(correlation_id: str = "corr") -> RawJobContext:
    return RawJobContext(correlation_id=correlation_id, discovered_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_new_url_creates_saga() -> None:
    """No saga exists for the URL -> create one and return is_new=True."""
    service = JobStoreService()
    db = _mock_db()

    mock_lookup = MagicMock()
    mock_lookup.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_lookup

    discovered = DiscoveredListing(listing_url="https://x/y", content_hash="h1")
    listing_ref = ListingReference(listing_url="https://x/y")

    saga = MagicMock()
    saga.id = uuid.uuid4()

    with (
        patch("job_storage_service.services.bank_service._saga_repo") as repo,
        patch("job_storage_service.services.bank_service.publish_listing_accepted_event", new_callable=AsyncMock),
    ):
        repo.create = AsyncMock(return_value=saga)
        result = await service.handle_discovered_listing(db, discovered, listing_ref, _ctx())

    assert result.is_new is True
    assert result.saga_id == saga.id
    repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_redelivery_same_content_hash_is_idempotent() -> None:
    """Same URL and same content_hash on a PENDING saga is a no-op update.

    Crucially, no second ListingAccepted event is published: redelivery is
    handled purely as Kafka idempotency, not as a fresh accept.
    """
    service = JobStoreService()
    db = _mock_db()

    existing_saga = MagicMock()
    existing_saga.id = uuid.uuid4()
    existing_saga.content_hash = "h1"

    mock_lookup = MagicMock()
    mock_lookup.scalar_one_or_none.return_value = existing_saga
    db.execute.return_value = mock_lookup

    discovered = DiscoveredListing(listing_url="https://x/y", content_hash="h1")
    listing_ref = ListingReference(listing_url="https://x/y")

    with (
        patch("job_storage_service.services.bank_service._saga_repo") as repo,
        patch(
            "job_storage_service.services.bank_service.publish_listing_accepted_event",
            new_callable=AsyncMock,
        ) as mock_publish,
    ):
        repo.create = AsyncMock()
        result = await service.handle_discovered_listing(db, discovered, listing_ref, _ctx())

    assert result.is_new is False
    assert result.saga_id == existing_saga.id
    repo.create.assert_not_awaited()
    mock_publish.assert_not_awaited()
    # No mutation of content_hash on idempotent redelivery.
    assert existing_saga.content_hash == "h1"


@pytest.mark.asyncio
async def test_url_revisit_with_new_hash_updates_in_place() -> None:
    """Same URL, different content_hash refreshes the saga payload in place."""
    service = JobStoreService()
    db = _mock_db()

    existing_saga = MagicMock()
    existing_saga.id = uuid.uuid4()
    existing_saga.content_hash = "h_old"

    mock_lookup = MagicMock()
    mock_lookup.scalar_one_or_none.return_value = existing_saga
    db.execute.return_value = mock_lookup

    discovered = DiscoveredListing(listing_url="https://x/y", content_hash="h_new")
    listing_ref = ListingReference(listing_url="https://x/y")

    with (
        patch("job_storage_service.services.bank_service._saga_repo") as repo,
        patch("job_storage_service.services.bank_service.publish_listing_accepted_event", new_callable=AsyncMock),
    ):
        repo.create = AsyncMock()
        result = await service.handle_discovered_listing(db, discovered, listing_ref, _ctx())

    assert result.is_new is False
    assert existing_saga.content_hash == "h_new"
    repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_saga_does_not_block_new_pending() -> None:
    """A previously COMPLETED saga should not appear in PENDING lookups.

    A new saga is created on rediscovery: this is enforced by the partial
    unique index in the DB; here we simulate by returning None from the PENDING lookup.
    """
    service = JobStoreService()
    db = _mock_db()

    mock_lookup = MagicMock()
    mock_lookup.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_lookup

    discovered = DiscoveredListing(listing_url="https://x/y", content_hash="h1")
    listing_ref = ListingReference(listing_url="https://x/y")

    new_saga = MagicMock()
    new_saga.id = uuid.uuid4()

    with (
        patch("job_storage_service.services.bank_service._saga_repo") as repo,
        patch("job_storage_service.services.bank_service.publish_listing_accepted_event", new_callable=AsyncMock),
    ):
        repo.create = AsyncMock(return_value=new_saga)
        result = await service.handle_discovered_listing(db, discovered, listing_ref, _ctx())

    assert result.is_new is True
    repo.create.assert_awaited_once()

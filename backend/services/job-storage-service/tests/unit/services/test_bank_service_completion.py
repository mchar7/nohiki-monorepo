"""Saga completion behavior for bank_stored_listing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_storage_service.db.models import Listing
from job_storage_service.services.bank_service import JobStoreService
from nohiki.common.v1 import JobBoardSource, ListingReference, ListingStatus
from nohiki.job.ingest.v1 import StoredListing
from nohiki.ml.v1 import DenseData, EmbeddingType, EmbeddingVector


def _mock_db() -> AsyncMock:
    mock = AsyncMock()
    mock.add = MagicMock()
    # ``expunge`` is sync on the real AsyncSession; force MagicMock so it is
    # not auto-coerced into an awaitable that AsyncMock would create.
    mock.expunge = MagicMock()
    return mock


def _stored() -> StoredListing:
    """Build a StoredListing satisfying listings table CHECK constraints.

    Description must be at least 200 chars (chk_description_length) and
    location must be a populated JSON object (chk_location_json), so we
    deliberately set both.
    """
    from nohiki.common.v1 import CountryCode, Location, LocationType

    return StoredListing(
        listing_url="https://x/y",
        content_hash="ch",
        description="x" * 250,
        location=Location(country=CountryCode.USA, location_type=LocationType.PHYSICAL),
        skills_embedding=EmbeddingVector(embedding_type=EmbeddingType.DENSE, dense=DenseData(values=[0.1] * 8)),
        title_embedding=EmbeddingVector(embedding_type=EmbeddingType.DENSE, dense=DenseData(values=[0.2] * 8)),
        retrieval_embeddings=[EmbeddingVector(embedding_type=EmbeddingType.DENSE, dense=DenseData(values=[0.3] * 8))],
    )


def _existing_listing(listing_id: uuid.UUID) -> Listing:
    now = datetime.now(UTC).replace(tzinfo=None)
    return Listing(
        id=listing_id,
        listing_url="https://x/y",
        job_board_source=JobBoardSource.INDEED,
        title="Old Title",
        company_name="OldCo",
        description="x" * 250,
        version=1,
        raw_content_hash="old",
        dedup_hash="dedup-existing",
        discovered_at=now,
        created_at=now,
        updated_at=now,
        status=ListingStatus.ACTIVE,
        skills_embedding=[0.1, 0.2],
        title_embedding=[0.3, 0.4],
        collection_version="v1",
    )


@pytest.mark.asyncio
async def test_no_saga_returns_orphan() -> None:
    """Absent saga -> orphan outcome, no listings write, no commit."""
    service = JobStoreService()
    db = _mock_db()

    mock_no_saga = MagicMock()
    mock_no_saga.scalar_one_or_none.return_value = None
    db.execute.return_value = mock_no_saga

    listing_ref = ListingReference(listing_url="https://x/y")

    outcome = await service.bank_stored_listing(
        db, _stored(), listing_ref, correlation_id="corr", collection_version="v1"
    )

    assert outcome.status == "orphan"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_saga_pending_inserts_new_listing_with_saga_id() -> None:
    """New canonical listing inserted with id = saga.id, saga marked COMPLETED."""
    service = JobStoreService()
    db = _mock_db()

    saga = MagicMock()
    saga.id = uuid.uuid4()
    saga.version = 1
    saga.expected_callbacks = 1
    saga.content_hash = "ch"
    saga.transition_to = MagicMock()

    new_row = MagicMock()
    new_row.id = saga.id
    fresh_listing = _existing_listing(saga.id)

    pending_lookup = MagicMock()
    pending_lookup.scalar_one_or_none.return_value = saga

    no_dedup_hit = MagicMock()
    no_dedup_hit.scalar_one_or_none.return_value = None

    no_url_hit = MagicMock()
    no_url_hit.scalar_one_or_none.return_value = None

    insert_returning = MagicMock()
    insert_returning.fetchone.return_value = new_row

    get_by_id = MagicMock()
    get_by_id.scalar_one_or_none.return_value = fresh_listing

    saga_update = MagicMock()
    saga_update.rowcount = 1

    db.execute.side_effect = [
        pending_lookup,
        no_dedup_hit,
        no_url_hit,
        insert_returning,
        get_by_id,
        saga_update,
    ]

    listing_ref = ListingReference(listing_url="https://x/y")

    calls: list[str] = []
    qdrant = MagicMock()
    qdrant.upsert_vector_points_batch = AsyncMock(side_effect=lambda *_: calls.append("upsert"))
    publisher = AsyncMock(side_effect=lambda *_args, **_kwargs: calls.append("publish"))
    with (
        patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant),
        patch("job_storage_service.services.bank_service.get_jobs_collection_name", return_value="jobs_v1"),
        patch("job_storage_service.services.bank_service.publish_listing_created_event", publisher),
        patch("job_storage_service.services.bank_service.publish_listing_updated_event", new_callable=AsyncMock),
    ):
        outcome = await service.bank_stored_listing(
            db, _stored(), listing_ref, correlation_id="corr", collection_version="v1"
        )

    assert outcome.status == "banked"
    assert outcome.listing_id == str(saga.id)
    assert outcome.was_updated is False
    saga.transition_to.assert_not_called()  # banking uses optimistic UPDATE, not in-memory transition
    db.commit.assert_awaited_once()

    assert calls == ["upsert", "publish"]
    assert qdrant.upsert_vector_points_batch.await_args is not None
    collection, points = qdrant.upsert_vector_points_batch.await_args.args
    assert collection == "jobs_v1"
    assert len(points) == 1
    point = points[0]
    assert point.point_id == str(saga.id)
    assert [(embedding.embedding_type, len(embedding.dense.values)) for embedding in point.embeddings] == [
        (EmbeddingType.DENSE, 8),
    ]
    assert point.payload.to_dict() == {
        "entity_id": str(saga.id),
        "entity_type": "job",
        "collection_version": "v1",
        "content_hash": "ch",
        "is_active": True,
        "title": "Old Title",
        "company_name": "OldCo",
        "description": "x" * 250,
    }


@pytest.mark.asyncio
async def test_saga_pending_with_cross_source_dedup_updates_existing() -> None:
    """Cross-source dedup hit -> UPDATE the matching row, complete the saga."""
    service = JobStoreService()
    db = _mock_db()

    saga = MagicMock()
    saga.id = uuid.uuid4()
    saga.version = 1
    saga.expected_callbacks = 1
    saga.content_hash = "ch"
    saga.transition_to = MagicMock()
    qdrant = MagicMock()
    qdrant.upsert_vector_points_batch = AsyncMock(return_value=1)

    existing_id = uuid.uuid4()
    existing = _existing_listing(existing_id)

    pending_lookup = MagicMock()
    pending_lookup.scalar_one_or_none.return_value = saga

    dedup_hit = MagicMock()
    dedup_hit.scalar_one_or_none.return_value = existing

    update_returning = MagicMock()
    update_row = MagicMock()
    update_row.id = existing_id
    update_returning.fetchone.return_value = update_row

    get_by_id = MagicMock()
    get_by_id.scalar_one_or_none.return_value = existing

    saga_update = MagicMock()
    saga_update.rowcount = 1

    db.execute.side_effect = [pending_lookup, dedup_hit, update_returning, get_by_id, saga_update]

    listing_ref = ListingReference(listing_url="https://x/y")

    with (
        patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant),
        patch("job_storage_service.services.bank_service.get_jobs_collection_name", return_value="jobs_v1"),
        patch("job_storage_service.services.bank_service.publish_listing_created_event", new_callable=AsyncMock),
        patch("job_storage_service.services.bank_service.publish_listing_updated_event", new_callable=AsyncMock),
        patch.object(service, "_store_version_history"),
    ):
        outcome = await service.bank_stored_listing(
            db, _stored(), listing_ref, correlation_id="corr", collection_version="v1"
        )

    assert outcome.status == "banked"
    # ID stays anchored to the previously banked row, not the new saga.
    assert outcome.listing_id == str(existing_id)
    assert outcome.was_updated is True
    saga.transition_to.assert_not_called()  # banking uses optimistic UPDATE, not in-memory transition


@pytest.mark.asyncio
async def test_saga_pending_with_url_fallback_updates_existing() -> None:
    """URL fallback: dedup_hash misses but a row with the same listing_url is updated in place."""
    service = JobStoreService()
    db = _mock_db()

    saga = MagicMock()
    saga.id = uuid.uuid4()
    saga.version = 1
    saga.expected_callbacks = 1
    saga.content_hash = "ch"
    saga.transition_to = MagicMock()

    existing_id = uuid.uuid4()
    existing = _existing_listing(existing_id)

    pending_lookup = MagicMock()
    pending_lookup.scalar_one_or_none.return_value = saga

    no_dedup_hit = MagicMock()
    no_dedup_hit.scalar_one_or_none.return_value = None

    url_hit = MagicMock()
    url_hit.scalar_one_or_none.return_value = existing

    update_returning = MagicMock()
    update_row = MagicMock()
    update_row.id = existing_id
    update_returning.fetchone.return_value = update_row

    get_by_id = MagicMock()
    get_by_id.scalar_one_or_none.return_value = existing

    saga_update = MagicMock()
    saga_update.rowcount = 1

    db.execute.side_effect = [pending_lookup, no_dedup_hit, url_hit, update_returning, get_by_id, saga_update]

    listing_ref = ListingReference(listing_url="https://x/y")

    qdrant = MagicMock()
    qdrant.upsert_vector_points_batch = AsyncMock(return_value=1)
    with (
        patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant),
        patch("job_storage_service.services.bank_service.get_jobs_collection_name", return_value="jobs_v1"),
        patch("job_storage_service.services.bank_service.publish_listing_created_event", new_callable=AsyncMock),
        patch("job_storage_service.services.bank_service.publish_listing_updated_event", new_callable=AsyncMock),
        patch.object(service, "_store_version_history"),
    ):
        outcome = await service.bank_stored_listing(
            db, _stored(), listing_ref, correlation_id="corr", collection_version="v1"
        )

    assert outcome.status == "banked"
    assert outcome.listing_id == str(existing_id)
    assert outcome.was_updated is True


@pytest.mark.asyncio
async def test_saga_replay_when_already_completed_is_idempotent() -> None:
    """Replay scenario: re-delivery of EnrichmentCompleted after COMPLETED returns 'replay'.

    The PENDING lookup misses (partial unique index) but the diagnostic any-status
    lookup finds the COMPLETED saga, so we classify the call as a replay.
    """
    service = JobStoreService()
    db = _mock_db()

    no_pending = MagicMock()
    no_pending.scalar_one_or_none.return_value = None

    completed_saga = MagicMock()
    completed_saga.id = uuid.uuid4()
    completed_saga.status = "COMPLETED"
    any_saga = MagicMock()
    any_saga.scalar_one_or_none.return_value = completed_saga

    db.execute.side_effect = [no_pending, any_saga]

    listing_ref = ListingReference(listing_url="https://x/y")
    qdrant = MagicMock()
    qdrant.upsert_vector_points_batch = AsyncMock()
    with patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant):
        outcome = await service.bank_stored_listing(
            db, _stored(), listing_ref, correlation_id="corr", collection_version="v1"
        )

    assert outcome.status == "replay"
    db.commit.assert_not_awaited()
    qdrant.upsert_vector_points_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_qdrant_failure_prevents_canonical_event_and_commit() -> None:
    """A listing cannot become searchable-by-event when its vector write failed."""
    service = JobStoreService()
    db = _mock_db()
    saga = MagicMock(id=uuid.uuid4(), version=1, expected_callbacks=1, content_hash="ch")
    pending_lookup = MagicMock()
    pending_lookup.scalar_one_or_none.return_value = saga
    db.execute.return_value = pending_lookup
    job = _existing_listing(saga.id)
    qdrant = MagicMock()
    qdrant.upsert_vector_points_batch = AsyncMock(side_effect=RuntimeError("qdrant unavailable"))
    publisher = AsyncMock()

    with (
        patch.object(service, "_get_job_by_dedup_hash", new=AsyncMock(return_value=None)),
        patch.object(service, "_get_job_by_url", new=AsyncMock(return_value=None)),
        patch.object(service, "_insert_new_listing", new=AsyncMock(return_value=str(saga.id))),
        patch.object(service, "get_job_by_id", new=AsyncMock(return_value=job)),
        patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant),
        patch("job_storage_service.services.bank_service.get_jobs_collection_name", return_value="jobs_v1"),
        patch("job_storage_service.services.bank_service.publish_listing_created_event", publisher),
        pytest.raises(RuntimeError, match="qdrant unavailable"),
    ):
        await service.bank_stored_listing(
            db, _stored(), ListingReference(listing_url="https://x/y"), correlation_id="corr", collection_version="v1"
        )

    publisher.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_removes_vector_before_event_and_commit() -> None:
    """Deletion removes the stable point before publishing canonical CDC."""
    service = JobStoreService()
    db = _mock_db()
    listing_id = str(uuid.uuid4())
    calls: list[str] = []
    qdrant = MagicMock()
    qdrant.delete_points = AsyncMock(side_effect=lambda *_: calls.append("delete"))
    publisher = AsyncMock(side_effect=lambda *_args, **_kwargs: calls.append("publish"))
    db.commit.side_effect = lambda: calls.append("commit")

    with (
        patch("job_storage_service.services.bank_service.get_qdrant_client", return_value=qdrant),
        patch("job_storage_service.services.bank_service.get_jobs_collection_name", return_value="jobs_v1"),
        patch("job_storage_service.services.bank_service.publish_listing_deleted_event", publisher),
    ):
        await service.delete_job(db, listing_id)

    qdrant.delete_points.assert_awaited_once_with("jobs_v1", [listing_id])
    assert calls == ["delete", "publish", "commit"]

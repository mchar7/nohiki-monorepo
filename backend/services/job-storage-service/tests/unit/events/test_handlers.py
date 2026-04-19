"""Unit tests for Kafka event handlers in job-storage-service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_storage_service.services.bank_service import BankOutcome, _SagaIngestResult
from nohiki.common.v1 import ProcessingStatus
from nohiki_common_exceptions import ValidationError
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


def _make_discovered_message(
    *,
    correlation_id: str = "corr-123",
    listing_url: str = "https://example.com/job/1",
    query_id: str = "query-1",
) -> MagicMock:
    """Build a mock ListingDiscovered message."""
    msg = MagicMock()
    msg.listing.listing_url = listing_url
    msg.query_id = query_id
    msg.metadata.correlation_id = correlation_id
    msg.discovered_at = MagicMock()
    msg.discovered_data = MagicMock()
    return msg


def _make_enrichment_message(
    *,
    correlation_id: str = "corr-456",
    listing_url: str = "https://example.com/job/2",
    status: ProcessingStatus = ProcessingStatus.COMPLETED,
    collection_version: str = "v1",
) -> MagicMock:
    """Build a mock EnrichmentCompleted message."""
    msg = MagicMock()
    msg.listing.listing_url = listing_url
    msg.metadata.correlation_id = correlation_id
    msg.result.status = status
    msg.result.error_message = ""
    msg.stored_data = MagicMock()
    msg.collection_version = collection_version
    return msg


class TestHandleJobRawFound:
    """Tests for handle_job_raw_found handler."""

    @pytest.mark.asyncio
    async def test_new_saga_accepted(self) -> None:
        """A new discovered listing creates a new saga row."""
        from job_storage_service.events.handlers import handle_job_raw_found

        message = _make_discovered_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        saga_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.handle_discovered_listing = AsyncMock(
            return_value=_SagaIngestResult(saga_id=saga_id, is_new=True),
        )

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_raw_found(message, context)

            mock_service.handle_discovered_listing.assert_called_once()
            mock_logger.info.assert_any_call(
                "Saga accepted (new in-flight ingest)",
                saga_id=str(saga_id),
                listing_url="https://example.com/job/1",
                correlation_id="corr-123",
            )

    @pytest.mark.asyncio
    async def test_existing_saga_reused(self) -> None:
        """A redelivered discovery for the same URL reuses the existing saga."""
        from job_storage_service.events.handlers import handle_job_raw_found

        message = _make_discovered_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        saga_id = uuid.uuid4()
        mock_service = MagicMock()
        mock_service.handle_discovered_listing = AsyncMock(
            return_value=_SagaIngestResult(saga_id=saga_id, is_new=False),
        )

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_raw_found(message, context)

            mock_logger.info.assert_any_call(
                "Saga existed (in-flight ingest reused)",
                saga_id=str(saga_id),
                listing_url="https://example.com/job/1",
                correlation_id="corr-123",
            )

    @pytest.mark.asyncio
    async def test_integrity_error_dedup(self) -> None:
        """IntegrityError from the partial unique index returns idempotently."""
        from job_storage_service.events.handlers import handle_job_raw_found

        message = _make_discovered_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        mock_service = MagicMock()
        mock_service.handle_discovered_listing = AsyncMock(side_effect=IntegrityError("dup", {}, Exception()))

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_raw_found(message, context)

            mock_logger.info.assert_any_call(
                "Saga insert race detected; treating as duplicate",
                listing_url="https://example.com/job/1",
                correlation_id="corr-123",
            )


class TestHandleJobProcessingCompleted:
    """Tests for handle_job_processing_completed handler."""

    @pytest.mark.asyncio
    async def test_failed_enrichment_skipped(self) -> None:
        """Failed enrichment result is logged and the saga is marked FAILED."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message(status=ProcessingStatus.FAILED)
        message.result.error.error_message = "LLM timeout"
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        # Pretend no saga is found so the FAILED saga path short-circuits.
        no_saga = MagicMock()
        no_saga.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=no_saga)

        with patch("job_storage_service.events.handlers.logger") as mock_logger:
            await handle_job_processing_completed(message, context)

            mock_logger.warning.assert_any_call(
                "Skipping failed enrichment",
                listing_url="https://example.com/job/2",
                error_message="LLM timeout",
                correlation_id="corr-456",
            )

    @pytest.mark.asyncio
    async def test_failed_enrichment_marks_saga_failed(self) -> None:
        """Failed enrichment with an in-flight saga calls SagaRepository.fail."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message(status=ProcessingStatus.FAILED)
        message.result.error.error_message = "LLM timeout"
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        saga_id = uuid.uuid4()
        saga_lookup = MagicMock()
        saga_lookup.scalar_one_or_none.return_value = saga_id
        mock_db.execute = AsyncMock(return_value=saga_lookup)

        with (
            patch("job_storage_service.events.handlers._saga_repo") as mock_repo,
            patch("job_storage_service.events.handlers.logger"),
        ):
            mock_repo.fail = AsyncMock()
            await handle_job_processing_completed(message, context)

            mock_repo.fail.assert_awaited_once()
            mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_new_listing_created(self) -> None:
        """Successful enrichment creates a new listing."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        mock_service = MagicMock()
        mock_service.bank_stored_listing = AsyncMock(
            return_value=BankOutcome(status="banked", listing_id="listing-10", was_updated=False)
        )

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_processing_completed(message, context)

            mock_service.bank_stored_listing.assert_called_once()
            mock_logger.info.assert_any_call(
                "Stored listing banked",
                action="created",
                listing_id="listing-10",
                listing_url="https://example.com/job/2",
                correlation_id="corr-456",
            )

    @pytest.mark.asyncio
    async def test_existing_listing_updated(self) -> None:
        """Successful enrichment updates an existing listing."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        mock_service = MagicMock()
        mock_service.bank_stored_listing = AsyncMock(
            return_value=BankOutcome(status="banked", listing_id="listing-11", was_updated=True)
        )

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_processing_completed(message, context)

            mock_logger.info.assert_any_call(
                "Stored listing banked",
                action="updated",
                listing_id="listing-11",
                listing_url="https://example.com/job/2",
                correlation_id="corr-456",
            )

    @pytest.mark.asyncio
    async def test_replay_outcome_logs_idempotent(self) -> None:
        """Replay outcome logs an idempotent line and does not re-bank."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        mock_service = MagicMock()
        mock_service.bank_stored_listing = AsyncMock(return_value=BankOutcome(status="replay"))

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_processing_completed(message, context)

            mock_logger.info.assert_any_call(
                "Stored listing replay (idempotent)",
                listing_url="https://example.com/job/2",
                correlation_id="corr-456",
            )

    @pytest.mark.asyncio
    async def test_orphan_outcome_raises_validation_error(self) -> None:
        """Orphan outcome raises ValidationError so the message is DLQ'd."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        mock_service = MagicMock()
        mock_service.bank_stored_listing = AsyncMock(return_value=BankOutcome(status="orphan"))

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger"),
            pytest.raises(ValidationError),
        ):
            await handle_job_processing_completed(message, context)

    @pytest.mark.asyncio
    async def test_integrity_error_unique_violation_treated_as_race(self) -> None:
        """Unique-violation IntegrityError is logged as a race resolution, not an error."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        orig = MagicMock()
        orig.sqlstate = "23505"
        mock_service = MagicMock()
        mock_service.bank_stored_listing = AsyncMock(side_effect=IntegrityError("dup", {}, orig))

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_processing_completed(message, context)

            mock_logger.info.assert_any_call(
                "Enriched listing race resolved upstream",
                listing_url="https://example.com/job/2",
                correlation_id="corr-456",
            )

    @pytest.mark.asyncio
    async def test_integrity_error_check_violation_logged_as_error(self) -> None:
        """CHECK violation is escalated: pre-flight validation should have caught it."""
        from job_storage_service.events.handlers import handle_job_processing_completed

        message = _make_enrichment_message()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        orig = MagicMock()
        orig.sqlstate = "23514"
        mock_service = MagicMock()
        mock_service.bank_stored_listing = AsyncMock(side_effect=IntegrityError("chk", {}, orig))

        with (
            patch(
                "job_storage_service.events.handlers.JobStoreService",
                return_value=mock_service,
            ),
            patch("job_storage_service.events.handlers.logger") as mock_logger,
        ):
            await handle_job_processing_completed(message, context)

            assert any("CHECK constraint violation" in str(c.args[0]) for c in mock_logger.error.call_args_list)

"""Unit tests for event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_discovery_service.events.handlers import (
    handle_discovery_triggered,
    start_event_consumer,
)
from nohiki.common.v1 import EventMetadata
from nohiki.job.ingest.v1 import IngestionQuery, IngestionTriggered
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from nohiki_kafka_client.handlers import DbSessionConfig
from nohiki_kafka_client.middleware.db_session import execute_with_db_session


def _make_context(db_session: MagicMock | None = None) -> MessageContext:
    """Build a real message context with the transaction-owned session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


@pytest.fixture
def mock_context() -> MessageContext:
    """Create a message context with a spec'd async database session."""
    return _make_context(create_mock_session())


class TestHandleDiscoveryTriggered:
    """Tests for handle_discovery_triggered handler."""

    @pytest.mark.asyncio
    async def test_raises_when_no_metadata(self, mock_context: MessageContext) -> None:
        """Raises ValueError when metadata is missing."""
        message = IngestionTriggered(
            query=IngestionQuery(query_id="q-1", search_keywords=["python"]),
        )

        with pytest.raises(ValueError, match="EventMetadata is required"):
            await handle_discovery_triggered(message, mock_context)

    @pytest.mark.asyncio
    async def test_raises_when_no_query(self, mock_context: MessageContext) -> None:
        """Raises ValueError when query is missing."""
        message = IngestionTriggered(
            metadata=EventMetadata(
                event_id="e-1",
                source_service="test",
                correlation_id="corr-1",
                version="v1",
            ),
        )

        with pytest.raises(ValueError, match="IngestionQuery is required"):
            await handle_discovery_triggered(message, mock_context)

    @pytest.mark.asyncio
    async def test_runs_discovery(self, mock_context: MessageContext) -> None:
        """Runs discovery when message is valid."""
        message = IngestionTriggered(
            metadata=EventMetadata(
                event_id="e-1",
                source_service="test",
                correlation_id="corr-1",
                version="v1",
            ),
            query=IngestionQuery(query_id="q-1", search_keywords=["python"]),
        )

        with (
            patch(
                "job_ingest_discovery_service.events.handlers.check_and_mark_processed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "job_ingest_discovery_service.events.handlers.run_discovery",
                new_callable=AsyncMock,
            ) as mock_run,
        ):
            await handle_discovery_triggered(message, mock_context)
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs["query"].query_id == "q-1"

    @pytest.mark.asyncio
    async def test_empty_keyword_query_is_acknowledged_without_provider_work(
        self,
        mock_context: MessageContext,
    ) -> None:
        """A legacy empty query has an explicit no-discovery outcome."""
        message = IngestionTriggered(
            metadata=EventMetadata(
                event_id="e-empty",
                source_service="test",
                correlation_id="corr-empty",
                version="v1",
            ),
            query=IngestionQuery(query_id="q-empty", search_keywords=[]),
        )

        with (
            patch(
                "job_ingest_discovery_service.events.handlers.check_and_mark_processed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "job_ingest_discovery_service.events.handlers.run_discovery",
                new_callable=AsyncMock,
            ) as run,
        ):
            await handle_discovery_triggered(message, mock_context)

        run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_completed_event_claim_skips_redelivery(self) -> None:
        """A committed deterministic claim prevents a second scrape."""
        message = IngestionTriggered(
            metadata=EventMetadata(
                event_id="12345678-1234-5678-1234-567812345678",
                source_service="test",
                correlation_id="corr-1",
                version="v1",
            ),
            query=IngestionQuery(query_id="q-1", search_keywords=["python"]),
        )
        db = create_mock_session()
        claimed = False
        completed = False
        claim_ids: list[object] = []

        async def claim(
            _db: object,
            _schema: object,
            event_id: object,
            _handler: object,
        ) -> bool:
            nonlocal claimed
            claim_ids.append(event_id)
            if claimed or completed:
                return False
            claimed = True
            return True

        async def commit() -> None:
            nonlocal claimed, completed
            claimed = False
            completed = True

        db.commit.side_effect = commit
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        context = _make_context()

        with (
            patch(
                "job_ingest_discovery_service.events.handlers.check_and_mark_processed",
                new_callable=AsyncMock,
                side_effect=claim,
            ) as mark,
            patch(
                "job_ingest_discovery_service.events.handlers.run_discovery",
                new_callable=AsyncMock,
            ) as run,
        ):
            await execute_with_db_session(
                handle_discovery_triggered,
                message,
                context,
                DbSessionConfig(),
                factory,
            )
            await execute_with_db_session(
                handle_discovery_triggered,
                message,
                _make_context(),
                DbSessionConfig(),
                factory,
            )

        assert completed is True
        assert run.await_count == 1
        assert mark.await_count == 2
        assert claim_ids[0] == claim_ids[1]

    @pytest.mark.asyncio
    async def test_publish_failure_rolls_back_command_claim_for_redelivery(
        self,
    ) -> None:
        """An unpublished listing keeps the processed-event claim replayable."""
        message = IngestionTriggered(
            metadata=EventMetadata(
                event_id="87654321-4321-8765-4321-876543218765",
                source_service="test",
                correlation_id="corr-1",
                version="v1",
            ),
            query=IngestionQuery(query_id="q-1", search_keywords=["python"]),
        )
        db = create_mock_session()
        claimed = False
        claim_ids: list[object] = []

        async def claim(
            _db: object,
            _schema: object,
            event_id: object,
            _handler: object,
        ) -> bool:
            nonlocal claimed
            claim_ids.append(event_id)
            if claimed:
                return False
            claimed = True
            return True

        async def rollback() -> None:
            nonlocal claimed
            claimed = False

        db.rollback.side_effect = rollback
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "job_ingest_discovery_service.events.handlers.check_and_mark_processed",
                new_callable=AsyncMock,
                side_effect=claim,
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._build_discovery_request",
                return_value=MagicMock(),
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._discover_from_all_sources",
                new_callable=AsyncMock,
                return_value=[MagicMock()],
            ),
            patch(
                "job_ingest_discovery_service.services.discovery_service._dedupe_and_publish",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("kafka down"), 1],
            ) as deliver,
        ):
            with pytest.raises(RuntimeError, match="kafka down"):
                await execute_with_db_session(
                    handle_discovery_triggered,
                    message,
                    _make_context(),
                    DbSessionConfig(),
                    factory,
                )
            await execute_with_db_session(
                handle_discovery_triggered,
                message,
                _make_context(),
                DbSessionConfig(),
                factory,
            )

        db.rollback.assert_awaited_once()
        db.commit.assert_awaited_once()
        assert deliver.await_count == 2
        assert claim_ids[0] == claim_ids[1]


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_consumers(self) -> None:
        """Starts Kafka consumers."""
        with patch("job_ingest_discovery_service.events.handlers.kafka_client") as mock_kafka:
            mock_kafka.start_consumers = MagicMock()
            start_event_consumer()
            mock_kafka.start_consumers.assert_called_once()

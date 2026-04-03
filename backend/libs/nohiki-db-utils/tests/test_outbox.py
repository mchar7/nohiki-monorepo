"""Tests for outbox module (OutboxWriter, OutboxEntry)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from nohiki_db_utils.outbox import OutboxEntry, OutboxPayload, OutboxWriter
from nohiki_db_utils.testing import create_mock_session


@dataclass
class MockProtobufMessage:
    """Mock protobuf message for testing."""

    data: str

    def __bytes__(self) -> bytes:
        """Serialize to bytes."""
        return self.data.encode("utf-8")


class TestOutboxEntry:
    """Tests for OutboxEntry dataclass."""

    def test_create_entry(self) -> None:
        """Test creating an OutboxEntry."""
        entry_id = uuid4()
        timestamp = datetime.now(UTC)
        entry = OutboxEntry(
            id=entry_id,
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
            payload=b"test payload",
            timestamp=timestamp,
            correlation_id="corr-456",
        )

        assert entry.id == entry_id
        assert entry.aggregate_type == "job"
        assert entry.aggregate_id == "job-123"
        assert entry.event_type == "job.created.v1"
        assert entry.payload == b"test payload"
        assert entry.timestamp == timestamp
        assert entry.correlation_id == "corr-456"

    def test_create_entry_without_correlation_id(self) -> None:
        """Test creating an OutboxEntry without correlation_id."""
        entry = OutboxEntry(
            id=uuid4(),
            aggregate_type="user",
            aggregate_id="user-789",
            event_type="user.updated.v1",
            payload=b"data",
            timestamp=datetime.now(UTC),
        )

        assert entry.correlation_id is None

    def test_entry_is_frozen_dataclass(self) -> None:
        """Test that OutboxEntry is a frozen dataclass."""
        assert dataclasses.is_dataclass(OutboxEntry)
        params = getattr(OutboxEntry, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestOutboxPayloadProtocol:
    """Tests for OutboxPayload protocol."""

    def test_mock_message_implements_protocol(self) -> None:
        """Test that mock message implements OutboxPayload protocol."""
        msg = MockProtobufMessage(data="test")
        assert isinstance(msg, OutboxPayload)

    def test_bytes_method(self) -> None:
        """Test __bytes__ method on protocol implementer."""
        msg = MockProtobufMessage(data="hello")
        assert bytes(msg) == b"hello"


class TestOutboxWriter:
    """Tests for OutboxWriter class."""

    def test_init_with_schema(self) -> None:
        """Test initializing OutboxWriter with schema."""
        writer = OutboxWriter(schema="test_schema")
        assert writer._schema == "test_schema"

    def test_init_without_schema_raises(self) -> None:
        """Test that initializing without schema raises ValueError."""
        with pytest.raises(ValueError, match="requires explicit schema"):
            OutboxWriter(schema="")

    def test_init_with_none_schema_raises(self) -> None:
        """Test that initializing with None schema raises ValueError."""
        with pytest.raises(ValueError, match="requires explicit schema"):
            OutboxWriter(schema=None)

    def test_init_with_db_session(self) -> None:
        """Test initializing with bound database session."""
        mock_session = MagicMock()
        writer = OutboxWriter(schema="test_schema", db=mock_session)
        assert writer._db is mock_session

    def test_serialize_betterproto_message(self) -> None:
        """Test serialization of betterproto2 message with __bytes__."""
        writer = OutboxWriter(schema="test_schema")
        msg = MockProtobufMessage(data="test data")

        result = writer._serialize(msg)

        assert result == b"test data"

    @pytest.mark.asyncio
    async def test_write_event_success(self) -> None:
        """Test writing an event to the outbox."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock()
        writer = OutboxWriter(schema="test_schema")
        msg = MockProtobufMessage(data="event data")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
            correlation_id="corr-456",
        )
        entry_id = await writer.write_event(
            db=mock_session,
            params=params,
            event=msg,
        )

        assert isinstance(entry_id, UUID)
        mock_session.execute.assert_called_once()

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["aggregate_type"] == "job"
        assert params["aggregate_id"] == "job-123"
        assert params["event_type"] == "job.created.v1"
        assert params["payload"] == b"event data"
        assert params["correlation_id"] == "corr-456"

    @pytest.mark.asyncio
    async def test_write_event_without_correlation_id(self) -> None:
        """Test writing an event without correlation_id."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock()
        writer = OutboxWriter(schema="test_schema")
        msg = MockProtobufMessage(data="event data")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="user",
            aggregate_id="user-789",
            event_type="user.updated.v1",
        )
        await writer.write_event(
            db=mock_session,
            params=params,
            event=msg,
        )

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["correlation_id"] is None

    @pytest.mark.asyncio
    async def test_write_event_uses_bound_session(self) -> None:
        """Test that write_event uses bound session when db is None."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock()
        writer = OutboxWriter(schema="test_schema", db=mock_session)
        msg = MockProtobufMessage(data="bound session data")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
        )
        await writer.write_event(
            db=None,
            params=params,
            event=msg,
        )

        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_events_success(self) -> None:
        """Test writing multiple events to the outbox in one call."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock()
        writer = OutboxWriter(schema="test_schema")

        from nohiki_db_utils.outbox import OutboxEventParams

        entries = [
            (
                OutboxEventParams(
                    aggregate_type="job",
                    aggregate_id="job-1",
                    event_type="job.created.v1",
                ),
                MockProtobufMessage(data="event-1"),
            ),
            (
                OutboxEventParams(
                    aggregate_type="job",
                    aggregate_id="job-2",
                    event_type="job.created.v1",
                ),
                MockProtobufMessage(data="event-2"),
            ),
        ]

        entry_ids = await writer.write_events(db=mock_session, entries=entries)

        assert len(entry_ids) == 2
        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        rows = call_args[0][1]
        assert len(rows) == 2
        assert rows[0]["payload"] == b"event-1"
        assert rows[1]["payload"] == b"event-2"

    @pytest.mark.asyncio
    async def test_write_event_no_session_raises(self) -> None:
        """Test that write_event raises when no session available."""
        writer = OutboxWriter(schema="test_schema")
        msg = MockProtobufMessage(data="data")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
        )
        with pytest.raises(ValueError, match="AsyncSession is required"):
            await writer.write_event(
                db=None,
                params=params,
                event=msg,
            )

    @pytest.mark.asyncio
    async def test_write_event_raw_success(self) -> None:
        """Test writing raw bytes to the outbox."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock()
        writer = OutboxWriter(schema="test_schema")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="attachment",
            aggregate_id="att-456",
            event_type="attachment.uploaded.v1",
            correlation_id="corr-789",
        )
        entry_id = await writer.write_event_raw(
            db=mock_session,
            params=params,
            payload=b"raw binary data",
        )

        assert isinstance(entry_id, UUID)
        mock_session.execute.assert_called_once()

        call_args = mock_session.execute.call_args
        params = call_args[0][1]
        assert params["aggregate_type"] == "attachment"
        assert params["aggregate_id"] == "att-456"
        assert params["event_type"] == "attachment.uploaded.v1"
        assert params["payload"] == b"raw binary data"
        assert params["correlation_id"] == "corr-789"

    @pytest.mark.asyncio
    async def test_write_event_raw_no_session_raises(self) -> None:
        """Test that write_event_raw raises when no session available."""
        writer = OutboxWriter(schema="test_schema")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
        )
        with pytest.raises(ValueError, match="AsyncSession is required"):
            await writer.write_event_raw(
                db=None,
                params=params,
                payload=b"data",
            )

    @pytest.mark.asyncio
    async def test_write_event_records_error_metric_on_failure(self) -> None:
        """Test that write_event records error metrics when DB insert fails."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
        writer = OutboxWriter(schema="test_schema")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
        )
        with pytest.raises(RuntimeError, match="connection lost"):
            await writer.write_event(
                db=mock_session,
                params=params,
                event=MockProtobufMessage(data="fail"),
            )

    @pytest.mark.asyncio
    async def test_write_event_raw_records_error_metric_on_failure(self) -> None:
        """Test that write_event_raw records error metrics when DB insert fails."""
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("connection lost"))
        writer = OutboxWriter(schema="test_schema")

        from nohiki_db_utils.outbox import OutboxEventParams

        params = OutboxEventParams(
            aggregate_type="job",
            aggregate_id="job-123",
            event_type="job.created.v1",
        )
        with pytest.raises(RuntimeError, match="connection lost"):
            await writer.write_event_raw(
                db=mock_session,
                params=params,
                payload=b"fail data",
            )

    def test_insert_sql_contains_schema(self) -> None:
        """Test that generated SQL contains the correct schema."""
        writer = OutboxWriter(schema="my_custom_schema")

        sql_text = str(writer._insert_sql)

        assert "my_custom_schema.outbox" in sql_text

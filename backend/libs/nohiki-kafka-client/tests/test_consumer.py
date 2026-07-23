"""Unit tests for KafkaConsumer with aiokafka."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import betterproto2
import pytest
from aiokafka import ConsumerRecord, TopicPartition
from aiokafka.errors import KafkaError
from nohiki_kafka_client.consumer import HealthStatus, KafkaConsumer
from nohiki_kafka_client.dlq import ConsumedMessage, ProcessingContext
from nohiki_kafka_client.exceptions import (
    ConsumerError,
    DLQPublishError,
    SerializationError,
)
from nohiki_kafka_client.handlers import MessageContext


async def _empty_aiter(_self: object = None) -> AsyncIterator[ConsumerRecord]:
    """Async iterator that yields nothing: simulates an empty consumer."""
    if False:
        yield _make_consumer_record()


@dataclass
class MockProtoMessage(betterproto2.Message):
    """Mock betterproto2 message for testing."""

    value: str = ""

    def __bytes__(self) -> bytes:
        """Serialize to bytes."""
        return self.value.encode("utf-8")

    @classmethod
    def parse(cls, data: bytes) -> MockProtoMessage:
        """Parse bytes into message."""
        return cls(value=data.decode("utf-8", errors="ignore") if data else "")


def _make_consumer_record(
    topic: str = "test-topic",
    partition: int = 0,
    offset: int = 100,
    timestamp: int | None = 1234567890000,
    headers: list[tuple[str, bytes]] | None = None,
    key: bytes | None = None,
    value: bytes | None = b"test",
) -> ConsumerRecord:
    """Create a mock ConsumerRecord for testing."""
    return ConsumerRecord(
        topic=topic,
        partition=partition,
        offset=offset,
        timestamp=timestamp if timestamp is not None else 0,
        timestamp_type=1,
        key=key,
        value=value,
        checksum=None,
        serialized_key_size=len(key) if key else -1,
        serialized_value_size=len(value) if value else -1,
        headers=headers or [],
    )


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock KafkaClientConfig."""
    config = MagicMock()
    config.consumer.group_id = "test-group"
    config.consumer.max_concurrent_handlers = 10
    config.consumer.max_poll_records = 500
    config.consumer.enable_auto_commit = False
    config.consumer.periodic_commit_interval_seconds = 5.0
    config.dlq = MagicMock()
    config.observability = MagicMock()
    return config


@pytest.fixture
def mock_dlq_handler() -> MagicMock:
    """Create mock DLQHandler."""
    handler = MagicMock()
    handler.handle_failure = AsyncMock()
    return handler


@pytest.fixture
def consumer(mock_config: MagicMock, mock_dlq_handler: MagicMock) -> KafkaConsumer:
    """Create KafkaConsumer instance for testing."""
    return KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)


class TestDeserializeMessage:
    """Tests for _deserialize_message helper."""

    def test_deserialize_message_success(self, consumer: KafkaConsumer) -> None:
        """Test successful message deserialization."""
        record = _make_consumer_record(
            headers=[("key1", b"value1")],
            key=b"test-key",
            value=b"test-value",
        )

        message, context = consumer._deserialize_message(record, MockProtoMessage)

        assert isinstance(message, MockProtoMessage)
        assert context.topic == "test-topic"
        assert context.partition == 0
        assert context.offset == 100
        assert context.timestamp == 1234567890000
        assert context.headers == {"key1": "value1"}
        assert context.key == "test-key"

    def test_deserialize_message_no_timestamp(self, consumer: KafkaConsumer) -> None:
        """Test deserialization when timestamp is None."""
        record = _make_consumer_record(timestamp=None, key=None, value=b"test")

        _, context = consumer._deserialize_message(record, MockProtoMessage)

        assert context.timestamp == 0
        assert context.key is None

    def test_deserialize_message_with_empty_headers(self, consumer: KafkaConsumer) -> None:
        """Test deserialization handles empty headers."""
        record = _make_consumer_record(headers=[], value=b"test")

        _, context = consumer._deserialize_message(record, MockProtoMessage)

        assert context.headers == {}

    def test_deserialize_message_none_value_raises(self, consumer: KafkaConsumer) -> None:
        """Deserialization raises when value is None."""
        record = _make_consumer_record(value=None)

        with pytest.raises(SerializationError, match="Message value is None"):
            consumer._deserialize_message(record, MockProtoMessage)


class TestBuildConsumedMessage:
    """Tests for _build_consumed_message helper."""

    def test_build_consumed_message(self, consumer: KafkaConsumer) -> None:
        """Test building ConsumedMessage from ConsumerRecord."""
        record = _make_consumer_record(
            partition=2,
            offset=500,
            timestamp=9876543210000,
            headers=[("h1", b"v1"), ("h2", b"v2")],
            key=b"msg-key",
            value=b"raw-payload",
        )

        result = consumer._build_consumed_message(record)

        assert isinstance(result, ConsumedMessage)
        assert result.topic == "test-topic"
        assert result.partition == 2
        assert result.offset == 500
        assert result.timestamp == 9876543210000
        assert result.headers == {"h1": "v1", "h2": "v2"}
        assert result.key == "msg-key"
        assert result.raw_value == b"raw-payload"


class TestExecuteHandlerWithTracing:
    """Tests for _execute_handler_with_tracing helper."""

    @pytest.mark.asyncio
    async def test_execute_handler_with_tracing_success(self, consumer: KafkaConsumer) -> None:
        """Test handler execution with tracing span."""
        handler = AsyncMock()
        message = MagicMock()
        context = MessageContext(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
        )

        await consumer._execute_handler_with_tracing(handler, message, context, MockProtoMessage)

        handler.assert_awaited_once_with(message, context)


class TestRecordProcessingMetrics:
    """Tests for _record_processing_metrics helper."""

    def test_record_metrics_increments_count_on_success(self, consumer: KafkaConsumer) -> None:
        """Metrics recording increments message count on success."""
        consumer._message_count = 0
        mock_metrics = MagicMock()
        consumer._metrics = mock_metrics

        context = MessageContext(
            topic="test-topic",
            partition=0,
            offset=100,
            timestamp=0,
            headers={},
            key=None,
        )

        consumer._record_processing_metrics(context, time.time() - 0.1, MockProtoMessage, success=True)

        assert consumer._message_count == 1
        mock_metrics.record_message_consumed.assert_called_once()

    def test_record_metrics_does_not_increment_on_failure(self, consumer: KafkaConsumer) -> None:
        """Metrics recording does not increment count on failure."""
        consumer._message_count = 5
        mock_metrics = MagicMock()
        consumer._metrics = mock_metrics

        context = MessageContext(
            topic="test-topic",
            partition=0,
            offset=100,
            timestamp=0,
            headers={},
            key=None,
        )

        consumer._record_processing_metrics(context, time.time() - 0.1, MockProtoMessage, success=False)

        assert consumer._message_count == 5
        mock_metrics.record_message_consumed.assert_called_once()


class TestHandleDlqFailure:
    """Tests for _handle_dlq_failure helper."""

    @pytest.mark.asyncio
    async def test_handle_dlq_failure_success(self, consumer: KafkaConsumer, mock_dlq_handler: MagicMock) -> None:
        """Test successful DLQ handling."""
        mock_dlq_handler.handle_failure.return_value = MagicMock(success=True)

        consumed_message = ConsumedMessage(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"test",
        )
        error = ValueError("test error")
        processing_context = ProcessingContext(
            consumer_group="test-group",
            handler_name="TestHandler",
            processing_start_time=time.time(),
        )

        await consumer._handle_dlq_failure(consumed_message, error, processing_context)

        mock_dlq_handler.handle_failure.assert_awaited_once()


class TestHealthStatus:
    """Tests for HealthStatus dataclass."""

    def test_create_health_status(self) -> None:
        """HealthStatus stores all fields."""
        status = HealthStatus(
            healthy=True,
            details={"key": "value"},
            last_check=1234567890.0,
        )
        assert status.healthy is True
        assert status.details == {"key": "value"}
        assert status.last_check == pytest.approx(1234567890.0)


class TestKafkaConsumerInit:
    """Tests for KafkaConsumer initialization."""

    def test_init_creates_consumer(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """KafkaConsumer initializes with config."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        assert consumer._config == mock_config
        assert consumer._dlq_handler == mock_dlq_handler
        assert consumer._consumer is None
        assert consumer._health_status.healthy is False

    def test_init_with_custom_group_id(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """KafkaConsumer uses custom group_id if provided."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler, group_id="custom-group")
        assert consumer._group_id == "custom-group"

    def test_init_uses_config_group_id(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """KafkaConsumer uses config group_id when not provided."""
        mock_config.consumer.group_id = "config-group"
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        assert consumer._group_id == "config-group"


class TestKafkaConsumerLifecycle:
    """Tests for KafkaConsumer lifecycle methods."""

    @pytest.mark.asyncio
    async def test_context_manager_initializes_and_cleans_up(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """Context manager initializes and cleans up consumer."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        with (
            patch.object(consumer, "_initialize", new_callable=AsyncMock) as mock_init,
            patch.object(consumer, "_cleanup", new_callable=AsyncMock) as mock_cleanup,
        ):
            async with consumer as c:
                assert c == consumer
                mock_init.assert_awaited_once()

            mock_cleanup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_stops_consumer(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_cleanup stops consumer."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.stop = AsyncMock()
        consumer._consumer = mock_aio_consumer

        await consumer._cleanup()

        mock_aio_consumer.stop.assert_awaited_once()
        assert consumer._consumer is None
        assert consumer._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_cleanup_handles_stop_error(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_cleanup handles stop errors gracefully."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.stop = AsyncMock(side_effect=KafkaError())
        consumer._consumer = mock_aio_consumer

        await consumer._cleanup()

        assert consumer._consumer is None


class TestConsumeMethod:
    """Tests for consume method."""

    @pytest.mark.asyncio
    async def test_consume_raises_when_not_initialized(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """Consume raises when consumer not initialized."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        async def handler(message: MockProtoMessage, context: MessageContext) -> None:
            """Test handler - not invoked due to error condition."""

        with pytest.raises(ConsumerError, match="Consumer not initialized"):
            await consumer.consume(["test-topic"], MockProtoMessage, handler)


class TestDispatchRecord:
    """Tests for _dispatch_record and _bounded_process."""

    @pytest.mark.asyncio
    async def test_dispatch_record_registers_and_completes_offset(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """_dispatch_record registers offset as inflight and marks completed after processing."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        record = _make_consumer_record(partition=0, offset=42)

        processed = []

        async def handler(rec: ConsumerRecord) -> None:
            await asyncio.sleep(0)
            processed.append(rec.offset)

        await consumer._dispatch_record(record, handler, preserve_partition_order=False)
        await consumer._drain_inflight()

        assert processed == [42]
        assert not await consumer._offset_tracker.has_pending()

    @pytest.mark.asyncio
    async def test_dlq_internal_failure_preserves_source_progress(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """An unsuccessful DLQ route leaves the source offset pending for redelivery."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        record = _make_consumer_record(topic="test.entity.failed.v1", partition=0, offset=99)
        handler = AsyncMock(side_effect=ValueError("handler failed"))
        mock_dlq_handler.handle_failure.return_value = MagicMock(
            success=False,
            error=OSError("DLQ unavailable"),
        )

        async def process_record(rec: ConsumerRecord) -> None:
            await consumer._process_message(rec, MockProtoMessage, handler)

        await consumer._dispatch_record(record, process_record, preserve_partition_order=False)
        with pytest.raises(DLQPublishError, match="DLQ handling failed"):
            await consumer._drain_inflight()

        handler.assert_awaited_once()
        mock_dlq_handler.handle_failure.assert_awaited_once()
        assert await consumer._offset_tracker.has_pending()
        assert await consumer._offset_tracker.get_committable_offsets() == {}


class TestConsumerStop:
    """Tests for stop method."""

    def test_stop_sets_shutdown_event(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """stop() sets the shutdown event."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        consumer.stop()

        assert consumer._shutdown_event.is_set()


class TestConsumerHealthCheck:
    """Tests for health_check method."""

    def test_health_check_returns_status(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """health_check returns current health status."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        status = consumer.health_check()

        assert status.healthy is False

    def test_health_check_with_initialized_consumer(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """health_check returns healthy after initialization."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.assignment = MagicMock(return_value={MagicMock()})
        consumer._consumer = mock_aio_consumer

        status = consumer.health_check()

        assert status.healthy is True
        assert status.details["assigned_partitions"] == 1

    def test_health_check_failure(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """health_check returns unhealthy on error."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.assignment = MagicMock(side_effect=KafkaError())
        consumer._consumer = mock_aio_consumer

        status = consumer.health_check()

        assert status.healthy is False


class TestConsumerInitialize:
    """Tests for consumer _initialize method."""

    @pytest.mark.asyncio
    @patch("nohiki_kafka_client.consumer.consumer.AIOKafkaConsumer")
    @patch("nohiki_kafka_client.consumer.consumer.get_aiokafka_consumer_config")
    async def test_initialize_success(
        self,
        mock_get_config: MagicMock,
        mock_consumer_cls: MagicMock,
        mock_config: MagicMock,
        mock_dlq_handler: MagicMock,
    ) -> None:
        """_initialize creates consumer successfully."""
        mock_get_config.return_value = {"bootstrap_servers": "localhost:29092"}
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.start = AsyncMock()
        mock_consumer_cls.return_value = mock_aio_consumer

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        await consumer._initialize()

        mock_aio_consumer.start.assert_awaited_once()
        assert consumer._consumer is mock_aio_consumer
        assert consumer._health_status.healthy is True

    @pytest.mark.asyncio
    @patch("nohiki_kafka_client.consumer.consumer.AIOKafkaConsumer")
    @patch("nohiki_kafka_client.consumer.consumer.get_aiokafka_consumer_config")
    async def test_initialize_failure(
        self,
        mock_get_config: MagicMock,
        mock_consumer_cls: MagicMock,
        mock_config: MagicMock,
        mock_dlq_handler: MagicMock,
    ) -> None:
        """_initialize raises ConsumerError on failure."""
        mock_get_config.return_value = {"bootstrap_servers": "localhost:29092"}
        mock_consumer_cls.side_effect = KafkaError()

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        with pytest.raises(ConsumerError, match="Failed to initialize"):
            await consumer._initialize()


class TestPartitionCallbacks:
    """Tests for partition assignment/revocation callbacks."""

    def test_on_partitions_assigned_logs(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_on_partitions_assigned logs assigned partitions (sync callback)."""
        from aiokafka import TopicPartition

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        partitions = {TopicPartition("test-topic", 0), TopicPartition("test-topic", 1)}

        with patch("nohiki_kafka_client.consumer.consumer.logger") as mock_logger:
            consumer._on_partitions_assigned(partitions)
            mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_partitions_revoked_skips_empty_set(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """_on_partitions_revoked returns immediately for empty revoked set (initial rebalance)."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer._manual_commit = True
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.commit = AsyncMock()
        consumer._consumer = mock_aio_consumer

        await consumer._on_partitions_revoked(set())

        mock_aio_consumer.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_partitions_revoked_skips_when_no_assignment(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """_on_partitions_revoked skips commit when consumer has no current assignment."""
        from aiokafka import TopicPartition

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer._manual_commit = True
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.commit = AsyncMock()
        mock_aio_consumer.assignment.return_value = set()
        consumer._consumer = mock_aio_consumer
        partitions = {TopicPartition("test-topic", 0)}

        await consumer._on_partitions_revoked(partitions)

        mock_aio_consumer.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_partitions_revoked_commits_when_manual(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """_on_partitions_revoked commits tracked contiguous offsets."""
        from aiokafka import TopicPartition

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer._manual_commit = True
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.commit = AsyncMock()
        consumer._consumer = mock_aio_consumer

        tp = TopicPartition("test-topic", 0)
        await consumer._offset_tracker.register_inflight(tp, 0)
        await consumer._offset_tracker.mark_completed(tp, 0)

        await consumer._on_partitions_revoked({tp})

        mock_aio_consumer.commit.assert_awaited_once_with({tp: 1})

    @pytest.mark.asyncio
    async def test_on_partitions_revoked_handles_commit_error(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """_on_partitions_revoked handles commit errors gracefully."""
        from aiokafka import TopicPartition
        from aiokafka.errors import KafkaError

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer._manual_commit = True
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.commit = AsyncMock(side_effect=KafkaError())
        consumer._consumer = mock_aio_consumer

        tp = TopicPartition("test-topic", 0)
        await consumer._offset_tracker.register_inflight(tp, 0)
        await consumer._offset_tracker.mark_completed(tp, 0)

        # Should not raise despite commit error
        await consumer._on_partitions_revoked({tp})


class TestConsumeLoop:
    """Tests for the consume loop."""

    @pytest.mark.asyncio
    async def test_consume_subscribes_to_topics(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """consume() subscribes to topics before iterating."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock()
        mock_aio_consumer.unsubscribe = MagicMock()
        mock_aio_consumer.__aiter__ = _empty_aiter
        consumer._consumer = mock_aio_consumer

        async def handler(message: MockProtoMessage, context: MessageContext) -> None:
            """Test handler - not invoked due to empty iterator."""

        await consumer.consume(["test-topic"], MockProtoMessage, handler)

        mock_aio_consumer.subscribe.assert_called_once()
        mock_aio_consumer.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_consume_handles_kafka_error(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """consume() raises ConsumerError on KafkaError."""
        from aiokafka.errors import KafkaError

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock(side_effect=KafkaError())
        mock_aio_consumer.unsubscribe = MagicMock()
        consumer._consumer = mock_aio_consumer

        async def handler(message: MockProtoMessage, context: MessageContext) -> None:
            """Test handler - not invoked due to error."""

        with pytest.raises(ConsumerError, match="Consumer loop failed"):
            await consumer.consume(["test-topic"], MockProtoMessage, handler)

    @pytest.mark.asyncio
    async def test_consume_handles_cancelled_error_with_graceful_drain(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """consume() drains in-flight work on cancellation then re-raises CancelledError."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock()
        mock_aio_consumer.unsubscribe = MagicMock()
        mock_aio_consumer.commit = AsyncMock()

        class _CancellingIter:
            def __aiter__(self) -> _CancellingIter:
                return self

            async def __anext__(self) -> ConsumerRecord:
                raise asyncio.CancelledError

        mock_aio_consumer.__aiter__ = lambda _self=None: _CancellingIter()
        consumer._consumer = mock_aio_consumer

        async def handler(message: MockProtoMessage, context: MessageContext) -> None:
            """Test handler - not invoked due to cancellation."""

        with pytest.raises(asyncio.CancelledError):
            await consumer.consume(["test-topic"], MockProtoMessage, handler)

        mock_aio_consumer.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_consume_stops_on_shutdown_event(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """consume() breaks out of iterator when shutdown event is set."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock()
        mock_aio_consumer.unsubscribe = MagicMock()
        mock_aio_consumer.commit = AsyncMock()

        record = _make_consumer_record()

        async def _aiter_impl(_self: object = None) -> AsyncIterator[ConsumerRecord]:
            consumer._shutdown_event.set()
            yield record

        mock_aio_consumer.__aiter__ = _aiter_impl
        consumer._consumer = mock_aio_consumer

        processed = []

        async def handler(_message: MockProtoMessage, _context: MessageContext) -> None:
            await asyncio.sleep(0)
            processed.append(True)

        await consumer.consume(["test-topic"], MockProtoMessage, handler)

        mock_aio_consumer.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_unexpected_record_failure_ends_generation_and_closes_consumer(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """A detached record failure cancels siblings and reaches the lifecycle owner."""
        mock_config.consumer.max_concurrent_handlers = 2
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        lifecycle: list[str] = []
        sibling_started = asyncio.Event()
        sibling_cancelled = asyncio.Event()
        failure_message = "detached record failed"

        async def _records(_self: object = None) -> AsyncIterator[ConsumerRecord]:
            yield _make_consumer_record(partition=0, offset=0)
            yield _make_consumer_record(partition=1, offset=0)
            await asyncio.Event().wait()

        async def _stop() -> None:
            lifecycle.append("stop")

        async def _process(record: ConsumerRecord) -> None:
            if record.partition == 0:
                await sibling_started.wait()
                raise RuntimeError(failure_message)
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        mock_aio_consumer.subscribe = MagicMock()
        mock_aio_consumer.unsubscribe = MagicMock(side_effect=lambda: lifecycle.append("unsubscribe"))
        mock_aio_consumer.stop = AsyncMock(side_effect=_stop)
        mock_aio_consumer.commit = AsyncMock()
        mock_aio_consumer.__aiter__ = _records
        consumer._consumer = mock_aio_consumer

        with (
            patch.object(consumer, "_initialize", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="detached record failed"),
        ):
            async with consumer:
                await asyncio.wait_for(
                    consumer._consume_loop(
                        ["test-topic"],
                        _process,
                        preserve_partition_order=False,
                    ),
                    timeout=1.0,
                )

        assert sibling_cancelled.is_set()
        assert not consumer._inflight_tasks
        assert lifecycle == ["unsubscribe", "stop"]
        mock_aio_consumer.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dlq_publish_failure_interrupts_generation_for_redelivery(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """A failed DLQ route stops advancement and cancels the live generation."""
        mock_config.consumer.max_concurrent_handlers = 2
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock()
        mock_aio_consumer.unsubscribe = MagicMock()
        mock_aio_consumer.commit = AsyncMock()
        sibling_started = asyncio.Event()
        sibling_cancelled = asyncio.Event()
        failure_message = "classified publish failure"

        async def _records(_self: object = None) -> AsyncIterator[ConsumerRecord]:
            yield _make_consumer_record(partition=0, offset=0)
            yield _make_consumer_record(partition=1, offset=0)
            await asyncio.Event().wait()

        async def _process(record: ConsumerRecord) -> None:
            if record.partition == 0:
                await sibling_started.wait()
                raise DLQPublishError(failure_message)
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        mock_aio_consumer.__aiter__ = _records
        consumer._consumer = mock_aio_consumer

        with pytest.raises(DLQPublishError, match=failure_message):
            await asyncio.wait_for(
                consumer._consume_loop(
                    ["test-topic"],
                    _process,
                    preserve_partition_order=False,
                ),
                timeout=1.0,
            )

        assert sibling_cancelled.is_set()
        assert not consumer._inflight_tasks
        assert await consumer._offset_tracker.has_pending()
        assert await consumer._offset_tracker.get_committable_offsets() == {}
        mock_aio_consumer.unsubscribe.assert_called_once()
        mock_aio_consumer.commit.assert_not_awaited()


class TestDrainInflight:
    """Tests for _drain_inflight method."""

    @pytest.mark.asyncio
    async def test_drain_waits_for_inflight_tasks(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_drain_inflight waits for all dispatched tasks to complete."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer._consumer = MagicMock()
        consumer._consumer.commit = AsyncMock()

        completed: list[bool] = []
        started = asyncio.Event()
        release = asyncio.Event()

        async def inflight_task() -> None:
            started.set()
            await release.wait()
            completed.append(True)

        task = asyncio.create_task(inflight_task())
        consumer._inflight_tasks.add(task)
        task.add_done_callback(consumer._inflight_tasks.discard)
        await started.wait()

        drain_task = asyncio.create_task(consumer._drain_inflight())
        asyncio.get_running_loop().call_soon(release.set)
        await drain_task

        assert completed == [True]
        assert len(consumer._inflight_tasks) == 0


class TestProcessMessage:
    """Tests for _process_message method."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::UserWarning")
    async def test_process_message_success(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_process_message processes message successfully."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        record = _make_consumer_record()
        mock_handler = AsyncMock()

        with (
            patch.object(consumer, "_execute_handler_with_tracing", new_callable=AsyncMock),
            patch.object(consumer, "_record_processing_metrics"),
        ):
            await consumer._process_message(record, MockProtoMessage, mock_handler)

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::UserWarning")
    async def test_process_message_error_handling(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_process_message handles errors via DLQ."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        record = _make_consumer_record(value=None)  # Causes SerializationError
        mock_handler = AsyncMock()

        with patch.object(consumer, "_handle_processing_error", new_callable=AsyncMock) as mock_handle_error:
            await consumer._process_message(record, MockProtoMessage, mock_handler)
            mock_handle_error.assert_awaited_once()


class TestConsumeMulti:
    """Tests for consume_multi method."""

    @pytest.mark.asyncio
    async def test_consume_multi_subscribes_and_iterates(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """consume_multi subscribes to topics and iterates messages."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock()
        mock_aio_consumer.unsubscribe = MagicMock()
        mock_aio_consumer.commit = AsyncMock()
        mock_aio_consumer.__aiter__ = _empty_aiter
        consumer._consumer = mock_aio_consumer

        handler_map = {"test-topic": MagicMock(handler=AsyncMock(), preserve_partition_order=True)}
        mock_kafka_client = MagicMock()

        await consumer.consume_multi(["test-topic"], handler_map, mock_kafka_client)

        mock_aio_consumer.subscribe.assert_called_once()
        mock_aio_consumer.unsubscribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_consume_multi_handles_kafka_error(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """consume_multi raises ConsumerError on KafkaError."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.subscribe = MagicMock(side_effect=KafkaError())
        mock_aio_consumer.unsubscribe = MagicMock()
        consumer._consumer = mock_aio_consumer

        handler_map = {"test-topic": MagicMock(handler=AsyncMock(), preserve_partition_order=True)}
        mock_kafka_client = MagicMock()

        with pytest.raises(ConsumerError, match="Consumer loop failed"):
            await consumer.consume_multi(["test-topic"], handler_map, mock_kafka_client)


class TestHealthAndMetrics:
    """Tests for health check and metrics methods."""

    def test_health_check_uninitialized(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """Health check returns unhealthy when consumer not initialized."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        status = consumer.health_check()
        assert not status.healthy
        assert "not initialized" in str(status.details.get("error", ""))

    def test_health_check_initialized(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """Health check returns healthy when consumer initialized."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        consumer._consumer = mock_aio_consumer
        status = consumer.health_check()
        assert status.healthy

    def test_stop_sets_shutdown_event(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """stop() method sets shutdown event."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer.stop()
        assert consumer._shutdown_event.is_set()


class TestConsumeForever:
    """Tests for consume_forever function."""

    @pytest.mark.asyncio
    async def test_consume_forever_creates_consumer(self, mock_config: MagicMock) -> None:
        """consume_forever creates consumer and calls consume."""
        from nohiki_kafka_client.consumer import ConsumeForeverOptions, consume_forever

        options = ConsumeForeverOptions(
            topics=["test-topic"],
            message_type=MockProtoMessage,
            handler=AsyncMock(),
            config=mock_config,
            group_id="test-group",
            shutdown_event=None,
        )

        with (
            patch("nohiki_kafka_client.consumer.consumer.KafkaConsumer") as mock_consumer_class,
            patch("nohiki_kafka_client.consumer.consumer.DLQHandler") as mock_dlq_handler_class,
        ):
            mock_consumer = MagicMock()
            mock_consumer.__aenter__ = AsyncMock(return_value=mock_consumer)
            mock_consumer.__aexit__ = AsyncMock()
            mock_consumer.consume = AsyncMock()
            mock_consumer_class.return_value = mock_consumer
            mock_dlq_handler_class.return_value = MagicMock()

            with patch("nohiki_kafka_client.consumer.consumer._run_consumer_with_shutdown") as mock_run:
                await consume_forever(options)
                mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_consume_forever_with_shutdown_event(self, mock_config: MagicMock) -> None:
        """consume_forever respects shutdown event."""
        from nohiki_kafka_client.consumer import ConsumeForeverOptions, consume_forever

        shutdown_event = asyncio.Event()
        shutdown_event.set()

        options = ConsumeForeverOptions(
            topics=["test-topic"],
            message_type=MockProtoMessage,
            handler=AsyncMock(),
            config=mock_config,
            group_id="test-group",
            shutdown_event=shutdown_event,
        )

        with (
            patch("nohiki_kafka_client.consumer.consumer.KafkaConsumer") as mock_consumer_class,
            patch("nohiki_kafka_client.consumer.consumer.DLQHandler") as mock_dlq_handler_class,
        ):
            mock_consumer = MagicMock()
            mock_consumer.__aenter__ = AsyncMock(return_value=mock_consumer)
            mock_consumer.__aexit__ = AsyncMock()
            mock_consumer.consume = AsyncMock()
            mock_consumer_class.return_value = mock_consumer
            mock_dlq_handler_class.return_value = MagicMock()

            await consume_forever(options)


class TestConcurrentProcessing:
    """Tests for concurrent processing via dispatch_record."""

    @pytest.mark.asyncio
    async def test_dispatch_processes_records_concurrently(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """Records dispatched without partition ordering run concurrently."""
        mock_config.consumer.max_concurrent_handlers = 3
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        records = [_make_consumer_record(partition=i, offset=i) for i in range(5)]
        call_order: list[int] = []

        async def process_record(record: ConsumerRecord) -> None:
            await asyncio.sleep(0)
            call_order.append(record.partition)

        for record in records:
            await consumer._dispatch_record(record, process_record, preserve_partition_order=False)

        await consumer._drain_inflight()

        assert sorted(call_order) == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_drain_commits_contiguous_offsets(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """_drain_inflight commits contiguous completed offsets via offset tracker."""
        from aiokafka import TopicPartition

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        mock_aio_consumer.commit = AsyncMock()
        consumer._consumer = mock_aio_consumer

        records = [_make_consumer_record(partition=0, offset=i) for i in range(3)]

        async def noop_process(_record: ConsumerRecord) -> None:
            await asyncio.sleep(0)

        for record in records:
            await consumer._dispatch_record(record, noop_process, preserve_partition_order=True)

        await consumer._drain_inflight()

        mock_aio_consumer.commit.assert_awaited_once()
        commit_arg = mock_aio_consumer.commit.call_args[0][0]
        tp = TopicPartition("test-topic", 0)
        assert commit_arg[tp] == 3


class TestPartitionOrdering:
    """Tests for partition-ordered processing."""

    @pytest.mark.asyncio
    async def test_partition_ordered_preserves_intra_partition_order(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """Records within the same partition are processed sequentially via partition lock."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        records = [_make_consumer_record(partition=0, offset=i) for i in range(5)]
        processing_order: list[int] = []

        async def track_order(record: ConsumerRecord) -> None:
            processing_order.append(record.offset)
            await asyncio.sleep(0)

        for record in records:
            await consumer._dispatch_record(record, track_order, preserve_partition_order=True)

        await consumer._drain_inflight()

        assert processing_order == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_different_partitions_run_concurrently(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """Records from different partitions can run concurrently."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)

        records = [
            _make_consumer_record(partition=0, offset=0),
            _make_consumer_record(partition=1, offset=0),
        ]
        started: list[int] = []

        async def track_partition(record: ConsumerRecord) -> None:
            await asyncio.sleep(0)
            started.append(record.partition)

        for record in records:
            await consumer._dispatch_record(record, track_partition, preserve_partition_order=True)

        await consumer._drain_inflight()

        assert set(started) == {0, 1}


class TestConsumerLag:
    """Tests for get_consumer_lag method."""

    @pytest.mark.asyncio
    async def test_get_consumer_lag_returns_empty_when_uninitialized(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """get_consumer_lag returns empty dict when consumer not initialized."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        assert await consumer.get_consumer_lag() == {}

    @pytest.mark.asyncio
    async def test_get_consumer_lag_calculates_per_partition(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """get_consumer_lag returns lag per topic-partition."""
        from aiokafka import TopicPartition

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()

        tp0 = TopicPartition("topic-a", 0)
        tp1 = TopicPartition("topic-a", 1)
        mock_aio_consumer.assignment.return_value = {tp0, tp1}
        mock_aio_consumer.committed = AsyncMock(side_effect=lambda tp: 10 if tp == tp0 else 20)
        mock_aio_consumer.end_offsets = AsyncMock(side_effect=lambda tps: {tps[0]: 50 if tps[0] == tp0 else 25})
        consumer._consumer = mock_aio_consumer

        lag = await consumer.get_consumer_lag()

        assert lag["topic-a:0"] == 40
        assert lag["topic-a:1"] == 5

    @pytest.mark.asyncio
    async def test_get_consumer_lag_skips_none_committed(
        self, mock_config: MagicMock, mock_dlq_handler: MagicMock
    ) -> None:
        """get_consumer_lag skips partitions with no committed offset."""
        from aiokafka import TopicPartition

        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()

        tp0 = TopicPartition("topic-a", 0)
        mock_aio_consumer.assignment.return_value = {tp0}
        mock_aio_consumer.committed = AsyncMock(return_value=None)
        mock_aio_consumer.end_offsets = AsyncMock(return_value={tp0: 100})
        consumer._consumer = mock_aio_consumer

        lag = await consumer.get_consumer_lag()

        assert lag == {}


class TestEnhancedHealthCheck:
    """Tests for enhanced health check details."""

    def test_health_check_includes_message_count(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """Health check includes messages_processed count."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        consumer._message_count = 42
        mock_aio_consumer = MagicMock()
        consumer._consumer = mock_aio_consumer

        status = consumer.health_check()

        assert status.healthy
        assert status.details["messages_processed"] == 42

    def test_health_check_includes_inflight_tasks(self, mock_config: MagicMock, mock_dlq_handler: MagicMock) -> None:
        """Health check includes inflight task count."""
        consumer = KafkaConsumer(config=mock_config, dlq_handler=mock_dlq_handler)
        mock_aio_consumer = MagicMock()
        consumer._consumer = mock_aio_consumer

        status = consumer.health_check()

        assert status.details["inflight_tasks"] == 0


class TestStartupOffsetSnapshot:
    """Tests for the durable startup catch-up primitives."""

    @pytest.mark.asyncio
    async def test_snapshot_waits_for_consumer_and_nonempty_assignment(self, consumer: KafkaConsumer) -> None:
        assert await consumer.snapshot_end_offsets() is None

        aio_consumer = MagicMock()
        aio_consumer.assignment.side_effect = [
            set(),
            {TopicPartition("events", 0)},
            {TopicPartition("events", 0)},
        ]
        aio_consumer.end_offsets = AsyncMock(return_value={TopicPartition("events", 0): 7})
        consumer._consumer = aio_consumer

        assert await consumer.snapshot_end_offsets() is None
        assert await consumer.snapshot_end_offsets() == {("events", 0): 7}
        aio_consumer.end_offsets.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snapshot_is_discarded_if_assignment_changes(self, consumer: KafkaConsumer) -> None:
        original = {TopicPartition("events", 0)}
        aio_consumer = MagicMock()
        aio_consumer.assignment.side_effect = [original, {TopicPartition("events", 1)}]
        aio_consumer.end_offsets = AsyncMock(return_value={TopicPartition("events", 0): 7})
        consumer._consumer = aio_consumer

        assert await consumer.snapshot_end_offsets() is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("committed", "target", "reached"),
        [(None, 0, True), (None, 1, False), (4, 5, False), (5, 5, True), (6, 5, True)],
    )
    async def test_reached_compares_committed_next_offset(
        self,
        consumer: KafkaConsumer,
        committed: int | None,
        target: int,
        *,
        reached: bool,
    ) -> None:
        partition = TopicPartition("events", 0)
        aio_consumer = MagicMock()
        aio_consumer.assignment.return_value = {partition}
        aio_consumer.committed = AsyncMock(return_value=committed)
        consumer._consumer = aio_consumer

        assert await consumer.has_reached_offsets({("events", 0): target}) is reached

    @pytest.mark.asyncio
    async def test_reached_is_false_for_uninitialized_or_changed_assignment(self, consumer: KafkaConsumer) -> None:
        snapshot = {("events", 0): 1}
        assert await consumer.has_reached_offsets(snapshot) is False

        aio_consumer = MagicMock()
        aio_consumer.assignment.return_value = {TopicPartition("events", 1)}
        consumer._consumer = aio_consumer
        assert await consumer.has_reached_offsets(snapshot) is False

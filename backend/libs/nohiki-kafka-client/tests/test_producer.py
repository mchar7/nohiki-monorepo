"""Unit tests for KafkaProducer with aiokafka."""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import betterproto2
import pytest
from aiokafka.errors import KafkaError
from nohiki_kafka_client.exceptions import CircuitBreakerOpenError, ProducerError
from nohiki_kafka_client.producer.producer import (
    BatchResult,
    HealthStatus,
    KafkaProducer,
    MessageMetadata,
    ProducerMessage,
    Transaction,
    _build_metadata_headers,
    _encode_headers,
    _PublishContext,
    _serialize_protobuf,
)
from nohiki_kafka_client.resilience import CircuitBreaker, CircuitState


@dataclass
class MockProtoMessage(betterproto2.Message):
    """Mock betterproto2 message for testing."""

    value: str = ""

    def __bytes__(self) -> bytes:
        """Serialize to bytes."""
        return self.value.encode("utf-8")


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock KafkaClientConfig."""
    config = MagicMock()
    config.client_id = "test-client"
    config.producer.enable_transactions = False
    config.producer.transactional_id = None
    config.producer.circuit_breaker = None
    return config


class TestEncodeHeaders:
    """Tests for _encode_headers helper."""

    def test_encode_headers_with_values(self) -> None:
        """Headers are encoded to bytes."""
        headers = {"key1": "value1", "key2": "value2"}
        result = _encode_headers(headers)
        assert result == [("key1", b"value1"), ("key2", b"value2")]

    def test_encode_headers_none(self) -> None:
        """None headers return None."""
        assert _encode_headers(None) is None

    def test_encode_headers_empty(self) -> None:
        """Empty dict returns None."""
        assert _encode_headers({}) is None


class TestSerializeProtobuf:
    """Tests for _serialize_protobuf helper."""

    def test_serialize_returns_bytes_and_time(self) -> None:
        """Serialization returns bytes and timing."""
        msg = MockProtoMessage(value="test")
        payload, elapsed_ms = _serialize_protobuf(msg)
        assert payload == b"test"
        assert elapsed_ms >= 0


class TestBuildMetadataHeaders:
    """Tests for _build_metadata_headers helper."""

    def test_build_headers_with_user_headers(self) -> None:
        """User headers are merged with metadata headers."""
        user_headers = {"custom": "value"}
        result = _build_metadata_headers("TestMessage", 1.5, user_headers)
        assert result["message_type"] == "TestMessage"
        assert result["custom"] == "value"
        assert "serialization_time_ms" in result
        assert "producer_timestamp" in result

    def test_build_headers_without_user_headers(self) -> None:
        """Only metadata headers when no user headers."""
        result = _build_metadata_headers("TestMessage", 1.5, None)
        assert len(result) == 3
        assert result["message_type"] == "TestMessage"


class TestPublishContext:
    """Tests for _PublishContext dataclass."""

    def test_create_context(self) -> None:
        """Context stores all fields."""
        ctx = _PublishContext(
            topic="test-topic",
            key="test-key",
            size_bytes=100,
            serialization_time_ms=1.5,
            start_time=1000.0,
        )
        assert ctx.topic == "test-topic"
        assert ctx.key == "test-key"
        assert ctx.size_bytes == 100


class TestMessageMetadata:
    """Tests for MessageMetadata dataclass."""

    def test_create_metadata(self) -> None:
        """MessageMetadata stores all fields."""
        metadata = MessageMetadata(
            topic="test-topic",
            partition=1,
            offset=100,
            timestamp=1234567890000,
            key="test-key",
            size_bytes=256,
            serialization_time_ms=1.5,
            publish_time_ms=10.0,
        )
        assert metadata.topic == "test-topic"
        assert metadata.partition == 1
        assert metadata.offset == 100


class TestProducerMessage:
    """Tests for ProducerMessage dataclass."""

    def test_create_producer_message(self) -> None:
        """ProducerMessage stores all fields."""
        msg = MockProtoMessage(value="test")
        producer_msg = ProducerMessage(message=msg, key="key", headers={"h": "v"})
        assert producer_msg.message == msg
        assert producer_msg.key == "key"
        assert producer_msg.headers == {"h": "v"}

    def test_producer_message_defaults(self) -> None:
        """ProducerMessage has correct defaults."""
        msg = MockProtoMessage(value="test")
        producer_msg = ProducerMessage(message=msg)
        assert producer_msg.key is None
        assert producer_msg.headers is None


class TestBatchResult:
    """Tests for BatchResult dataclass."""

    def test_create_batch_result(self) -> None:
        """BatchResult stores all fields."""
        result = BatchResult(
            successful_count=5,
            failed_count=1,
            total_size_bytes=1024,
            processing_time_ms=100.0,
        )
        assert result.successful_count == 5
        assert result.failed_count == 1
        assert result.errors == []
        assert result.metadata == []


class TestCircuitState:
    """Tests for CircuitState enum."""

    def test_enum_values(self) -> None:
        """CircuitState has expected values."""
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    @pytest.fixture
    def mock_cb_config(self) -> MagicMock:
        """Create mock CircuitBreakerConfig."""
        config = MagicMock()
        config.failure_threshold = 3
        config.timeout_seconds = 30.0
        return config

    def test_init_creates_breaker(self, mock_cb_config: MagicMock) -> None:
        """CircuitBreaker initializes with config."""
        breaker = CircuitBreaker(mock_cb_config)
        assert breaker._failure_threshold == 3
        assert breaker._recovery_timeout == pytest.approx(30.0)
        assert breaker._state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_cb_config: MagicMock) -> None:
        """Circuit breaker allows calls when closed."""
        breaker = CircuitBreaker(mock_cb_config)
        mock_operation = AsyncMock(return_value="success")

        result = await breaker.execute(mock_operation)

        assert result == "success"
        mock_operation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_opens_on_failures(self, mock_cb_config: MagicMock) -> None:
        """Circuit breaker opens after threshold failures."""
        mock_cb_config.failure_threshold = 2
        breaker = CircuitBreaker(mock_cb_config)
        mock_operation = AsyncMock(side_effect=ValueError("fail"))

        for _ in range(2):
            with pytest.raises(ValueError, match="fail"):
                await breaker.execute(mock_operation)

        assert breaker._state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_execute_raises_when_open(self, mock_cb_config: MagicMock) -> None:
        """Circuit breaker raises when open."""
        breaker = CircuitBreaker(mock_cb_config)
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.time()
        mock_operation = AsyncMock(return_value="x")

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.execute(mock_operation)

        mock_operation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_half_open_recovers_on_success(self, mock_cb_config: MagicMock) -> None:
        """Circuit breaker recovers from half-open on success."""
        breaker = CircuitBreaker(mock_cb_config)
        breaker._state = CircuitState.HALF_OPEN
        mock_operation = AsyncMock(return_value="ok")

        await breaker.execute(mock_operation)

        assert breaker._state == CircuitState.CLOSED
        assert breaker._failure_count == 0
        mock_operation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_open_transitions_to_half_open_after_timeout(self, mock_cb_config: MagicMock) -> None:
        """Circuit breaker transitions from OPEN to HALF_OPEN after recovery timeout."""
        mock_cb_config.timeout_seconds = 0.01
        breaker = CircuitBreaker(mock_cb_config)
        breaker._state = CircuitState.OPEN
        breaker._last_failure_time = time.perf_counter() - 1.0
        mock_operation = AsyncMock(return_value="recovered")

        result = await breaker.execute(mock_operation)

        assert result == "recovered"
        assert breaker._state == CircuitState.CLOSED
        mock_operation.assert_awaited_once()


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


class TestTransaction:
    """Tests for Transaction class."""

    @pytest.fixture
    def mock_aio_producer(self) -> MagicMock:
        """Create mock AIOKafkaProducer."""
        producer = MagicMock()
        producer.begin_transaction = AsyncMock()
        producer.commit_transaction = AsyncMock()
        producer.abort_transaction = AsyncMock()
        return producer

    def test_init_creates_transaction(self, mock_aio_producer: MagicMock) -> None:
        """Transaction initializes with producer and ID."""
        txn = Transaction(mock_aio_producer, "txn-123")
        assert txn._producer == mock_aio_producer
        assert txn._transaction_id == "txn-123"
        assert txn._active is False

    @pytest.mark.asyncio
    async def test_transaction_context_manager_success(self, mock_aio_producer: MagicMock) -> None:
        """Transaction commits on successful exit."""
        txn = Transaction(mock_aio_producer, "txn-123")

        async with txn:
            assert txn._active is True
            mock_aio_producer.begin_transaction.assert_awaited_once()

        mock_aio_producer.commit_transaction.assert_awaited_once()
        assert txn._active is False

    @pytest.mark.asyncio
    async def test_transaction_context_manager_exception(self, mock_aio_producer: MagicMock) -> None:
        """Transaction aborts on exception."""
        txn = Transaction(mock_aio_producer, "txn-123")

        err_msg = "test"
        with pytest.raises(ValueError, match=err_msg):
            async with txn:
                raise ValueError(err_msg)

        mock_aio_producer.abort_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_abort_when_active(self, mock_aio_producer: MagicMock) -> None:
        """abort() aborts when transaction is active."""
        txn = Transaction(mock_aio_producer, "txn-123")
        txn._active = True
        await txn.abort()

        mock_aio_producer.abort_transaction.assert_awaited_once()
        assert txn._active is False

    @pytest.mark.asyncio
    async def test_abort_when_inactive(self, mock_aio_producer: MagicMock) -> None:
        """abort() does nothing when transaction is inactive."""
        txn = Transaction(mock_aio_producer, "txn-123")
        txn._active = False
        await txn.abort()

        mock_aio_producer.abort_transaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transaction_begin_failure(self, mock_aio_producer: MagicMock) -> None:
        """Transaction raises ProducerError when begin_transaction fails."""
        mock_aio_producer.begin_transaction.side_effect = KafkaError()
        txn = Transaction(mock_aio_producer, "txn-123")

        with pytest.raises(ProducerError, match="Failed to start transaction"):
            async with txn:
                ...

    @pytest.mark.asyncio
    async def test_transaction_aexit_when_inactive(self, mock_aio_producer: MagicMock) -> None:
        """Transaction __aexit__ returns early when inactive."""
        txn = Transaction(mock_aio_producer, "txn-123")
        txn._active = False

        await txn.__aexit__(None, None, None)

        mock_aio_producer.commit_transaction.assert_not_awaited()
        mock_aio_producer.abort_transaction.assert_not_awaited()


class TestKafkaProducerInit:
    """Tests for KafkaProducer initialization."""

    def test_init_creates_producer(self, mock_config: MagicMock) -> None:
        """KafkaProducer initializes with config."""
        producer = KafkaProducer(mock_config)
        assert producer._config == mock_config
        assert producer._producer is None

    def test_init_with_circuit_breaker(self, mock_config: MagicMock) -> None:
        """KafkaProducer creates circuit breaker if configured."""
        mock_config.producer.circuit_breaker = MagicMock()
        mock_config.producer.circuit_breaker.failure_threshold = 5
        mock_config.producer.circuit_breaker.timeout_seconds = 60.0
        producer = KafkaProducer(mock_config)
        assert producer._circuit_breaker is not None


class TestKafkaProducerLifecycle:
    """Tests for KafkaProducer lifecycle methods."""

    @pytest.mark.asyncio
    @patch("nohiki_kafka_client.producer.producer.AIOKafkaProducer")
    @patch("nohiki_kafka_client.producer.producer.get_aiokafka_producer_config")
    async def test_context_manager_initializes_and_cleans_up(
        self, mock_get_config: MagicMock, mock_producer_cls: MagicMock, mock_config: MagicMock
    ) -> None:
        """Context manager initializes and cleans up producer."""
        mock_get_config.return_value = {"bootstrap_servers": "localhost:29092"}
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.start = AsyncMock()
        mock_kafka_producer.stop = AsyncMock()
        mock_producer_cls.return_value = mock_kafka_producer

        producer = KafkaProducer(mock_config)
        async with producer as p:
            assert p == producer
            mock_producer_cls.assert_called_once()

        mock_kafka_producer.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_stops_producer(self, mock_config: MagicMock) -> None:
        """_cleanup stops producer."""
        producer = KafkaProducer(mock_config)
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.stop = AsyncMock()
        producer._producer = mock_kafka_producer

        await producer._cleanup()

        mock_kafka_producer.stop.assert_awaited_once()
        assert producer._producer is None

    @pytest.mark.asyncio
    async def test_cleanup_handles_stop_error(self, mock_config: MagicMock) -> None:
        """_cleanup handles stop errors gracefully."""
        producer = KafkaProducer(mock_config)
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.stop = AsyncMock(side_effect=KafkaError())
        producer._producer = mock_kafka_producer

        await producer._cleanup()

        assert producer._producer is None


class TestProducerHealthCheck:
    """Tests for producer health check."""

    @pytest.mark.asyncio
    async def test_health_check_no_producer(self, mock_config: MagicMock) -> None:
        """health_check returns unhealthy when no producer."""
        producer = KafkaProducer(mock_config)

        status = await producer.health_check()

        assert status.healthy is False
        assert "Producer not initialized" in str(status.details["error"])

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_config: MagicMock) -> None:
        """health_check returns healthy on success."""
        producer = KafkaProducer(mock_config)
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.partitions_for = AsyncMock(return_value={0, 1, 2})
        producer._producer = mock_kafka_producer

        status = await producer.health_check()

        assert status.healthy is True
        assert status.details["partition_count"] == 3

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_config: MagicMock) -> None:
        """health_check returns unhealthy on failure."""
        producer = KafkaProducer(mock_config)
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.partitions_for = AsyncMock(side_effect=KafkaError())
        producer._producer = mock_kafka_producer

        status = await producer.health_check()

        assert status.healthy is False


class TestProducerFlush:
    """Tests for flush method."""

    @pytest.mark.asyncio
    async def test_flush_with_producer(self, mock_config: MagicMock) -> None:
        """flush() calls producer flush."""
        producer = KafkaProducer(mock_config)
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.flush = AsyncMock()
        producer._producer = mock_kafka_producer

        await producer.flush()

        mock_kafka_producer.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_without_producer(self, mock_config: MagicMock) -> None:
        """flush() does nothing without producer."""
        producer = KafkaProducer(mock_config)
        await producer.flush()


class TestBeginTransaction:
    """Tests for begin_transaction."""

    def test_begin_transaction_no_producer(self, mock_config: MagicMock) -> None:
        """begin_transaction raises when no producer."""
        producer = KafkaProducer(mock_config)

        with pytest.raises(ProducerError, match="Producer not initialized"):
            producer.begin_transaction()

    def test_begin_transaction_not_enabled(self, mock_config: MagicMock) -> None:
        """begin_transaction raises when transactions not enabled."""
        mock_config.producer.enable_transactions = False
        producer = KafkaProducer(mock_config)
        producer._producer = MagicMock()

        with pytest.raises(ProducerError, match="Transactions not enabled"):
            producer.begin_transaction()

    def test_begin_transaction_no_id(self, mock_config: MagicMock) -> None:
        """begin_transaction raises when no transactional ID."""
        mock_config.producer.enable_transactions = True
        mock_config.producer.transactional_id = None
        producer = KafkaProducer(mock_config)
        producer._producer = MagicMock()

        with pytest.raises(ProducerError, match="Transactional ID is required"):
            producer.begin_transaction()

    def test_begin_transaction_success(self, mock_config: MagicMock) -> None:
        """begin_transaction returns Transaction."""
        mock_config.producer.enable_transactions = True
        mock_config.producer.transactional_id = "txn-123"
        producer = KafkaProducer(mock_config)
        producer._producer = MagicMock()

        txn = producer.begin_transaction()

        assert isinstance(txn, Transaction)
        assert txn._transaction_id == "txn-123"


class TestProducerInitialization:
    """Tests for producer initialization."""

    @pytest.mark.asyncio
    @patch("nohiki_kafka_client.producer.producer.AIOKafkaProducer")
    @patch("nohiki_kafka_client.producer.producer.get_aiokafka_producer_config")
    async def test_initialize_success(
        self,
        mock_get_config: MagicMock,
        mock_producer_cls: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """_initialize creates and starts producer."""
        mock_get_config.return_value = {"bootstrap_servers": "localhost:29092"}
        mock_kafka_producer = MagicMock()
        mock_kafka_producer.start = AsyncMock()
        mock_producer_cls.return_value = mock_kafka_producer

        producer = KafkaProducer(mock_config)
        await producer._initialize()

        mock_kafka_producer.start.assert_awaited_once()
        assert producer._producer is mock_kafka_producer

    @pytest.mark.asyncio
    @patch("nohiki_kafka_client.producer.producer.AIOKafkaProducer")
    @patch("nohiki_kafka_client.producer.producer.get_aiokafka_producer_config")
    async def test_initialize_failure(
        self,
        mock_get_config: MagicMock,
        mock_producer_cls: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """_initialize raises ProducerError on failure."""
        mock_get_config.return_value = {"bootstrap_servers": "localhost:29092"}
        mock_producer_cls.side_effect = KafkaError()

        producer = KafkaProducer(mock_config)

        with pytest.raises(ProducerError, match="Failed to initialize"):
            await producer._initialize()


class TestPublish:
    """Tests for publish method."""

    @pytest.mark.asyncio
    async def test_publish_raises_when_not_initialized(self, mock_config: MagicMock) -> None:
        """Publish raises when producer not initialized."""
        producer = KafkaProducer(mock_config)
        msg = MockProtoMessage(value="test")

        with pytest.raises(ProducerError, match="Producer not initialized"):
            await producer.publish("topic", msg)

    @pytest.mark.asyncio
    async def test_publish_success(self, mock_config: MagicMock) -> None:
        """Publish returns metadata on success."""
        producer = KafkaProducer(mock_config)

        mock_record_metadata = MagicMock()
        mock_record_metadata.partition = 1
        mock_record_metadata.offset = 100
        mock_record_metadata.timestamp = 1234567890000

        mock_producer_obj = MagicMock()
        mock_producer_obj.send_and_wait = AsyncMock(return_value=mock_record_metadata)
        producer._producer = mock_producer_obj

        msg = MockProtoMessage(value="test")
        metadata = await producer.publish("test-topic", msg, key="test-key")

        assert metadata.topic == "test-topic"
        assert metadata.partition == 1
        assert metadata.offset == 100
        assert metadata.key == "test-key"


class TestPublishRaw:
    """Tests for publish_raw method."""

    @pytest.mark.asyncio
    async def test_publish_raw_raises_when_not_initialized(self, mock_config: MagicMock) -> None:
        """publish_raw raises when producer not initialized."""
        producer = KafkaProducer(mock_config)

        with pytest.raises(ProducerError, match="Producer not initialized"):
            await producer.publish_raw("topic", "key", b"value")

    @pytest.mark.asyncio
    async def test_publish_raw_success(self, mock_config: MagicMock) -> None:
        """publish_raw returns metadata on success."""
        producer = KafkaProducer(mock_config)

        mock_record_metadata = MagicMock()
        mock_record_metadata.partition = 0
        mock_record_metadata.offset = 50
        mock_record_metadata.timestamp = 1234567890000

        mock_producer_obj = MagicMock()
        mock_producer_obj.send_and_wait = AsyncMock(return_value=mock_record_metadata)
        producer._producer = mock_producer_obj

        metadata = await producer.publish_raw(
            "test-topic",
            "test-key",
            b"raw-value",
            headers={"dlq-source": "test"},
        )

        assert metadata.topic == "test-topic"
        assert metadata.partition == 0
        assert metadata.offset == 50


class TestPublishJson:
    """Tests for publish_json method."""

    @pytest.mark.asyncio
    async def test_publish_json_serialization_error(self, mock_config: MagicMock) -> None:
        """publish_json raises on serialization error."""
        producer = KafkaProducer(mock_config)
        producer._producer = MagicMock()

        class NotSerializable:
            pass

        with pytest.raises(ProducerError, match="Failed to serialize JSON"):
            await producer.publish_json("topic", {"bad": NotSerializable()})


class TestPublishBatch:
    """Tests for publish_batch method."""

    @pytest.mark.asyncio
    async def test_publish_batch_raises_when_not_initialized(self, mock_config: MagicMock) -> None:
        """publish_batch raises when producer not initialized."""
        producer = KafkaProducer(mock_config)

        with pytest.raises(ProducerError, match="Producer not initialized"):
            await producer.publish_batch("topic", [])

    @pytest.mark.asyncio
    async def test_publish_batch_raises_when_transactions_disabled(self, mock_config: MagicMock) -> None:
        """publish_batch raises when transactions not enabled."""
        mock_config.producer.enable_transactions = False
        producer = KafkaProducer(mock_config)
        producer._producer = MagicMock()

        with pytest.raises(ProducerError, match="requires transactional"):
            await producer.publish_batch("topic", [])


class TestIsReady:
    """Tests for is_ready method."""

    def test_is_ready_false_when_no_producer(self, mock_config: MagicMock) -> None:
        """is_ready returns False when producer is None."""
        producer = KafkaProducer(mock_config)
        assert producer.is_ready() is False

    def test_is_ready_true_when_producer_exists(self, mock_config: MagicMock) -> None:
        """is_ready returns True when producer exists."""
        producer = KafkaProducer(mock_config)
        producer._producer = MagicMock()
        assert producer.is_ready() is True

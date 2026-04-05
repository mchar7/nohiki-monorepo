"""Async Kafka producer using aiokafka with full header support."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn, Self

import betterproto2
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from nohiki_observability import get_logger

from nohiki_kafka_client.config import KafkaClientConfig, get_aiokafka_producer_config
from nohiki_kafka_client.exceptions import CircuitBreakerOpenError, ProducerError
from nohiki_kafka_client.handlers import CircuitBreakerConfig
from nohiki_kafka_client.observability.metrics import KafkaMetrics, get_kafka_metrics
from nohiki_kafka_client.producer.transaction import Transaction
from nohiki_kafka_client.resilience import CircuitBreaker, CircuitState

__all__ = [
    "BatchResult",
    "CircuitBreaker",
    "CircuitState",
    "HealthStatus",
    "KafkaProducer",
    "MessageMetadata",
    "ProducerMessage",
    "Transaction",
]

if TYPE_CHECKING:
    import types

logger = get_logger(__name__)

DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0
ERR_PRODUCER_NOT_INITIALIZED = "Producer not initialized"
ERR_BATCH_REQUIRES_TRANSACTIONS = "Batch publishing requires transactional producer"
ERR_TRANSACTIONS_NOT_ENABLED = "Transactions not enabled for this producer"
ERR_TRANSACTIONAL_ID_REQUIRED = "Transactional ID is required for transactions"


@dataclass(frozen=True, slots=True)
class MessageMetadata:
    """Immutable metadata about a published message."""

    topic: str
    partition: int
    offset: int
    timestamp: int
    key: str | None
    size_bytes: int
    serialization_time_ms: float
    publish_time_ms: float


@dataclass(frozen=True, slots=True)
class ProducerMessage:
    """Immutable message to be published in a batch."""

    message: betterproto2.Message
    key: str | None = None
    headers: dict[str, str] | None = None


@dataclass(slots=True)
class BatchResult:
    """Result of batch publishing."""

    successful_count: int
    failed_count: int
    total_size_bytes: int
    processing_time_ms: float
    metadata: list[MessageMetadata] = field(default_factory=list)
    errors: list[ProducerError] = field(default_factory=list)


@dataclass(slots=True)
class HealthStatus:
    """Producer health status."""

    healthy: bool
    details: dict[str, object]
    last_check: float


def _encode_headers(headers: dict[str, str] | None) -> list[tuple[str, bytes]] | None:
    """Convert string headers dict to Kafka header format."""
    if not headers:
        return None
    return [(k, v.encode("utf-8")) for k, v in headers.items()]


def _serialize_protobuf(message: betterproto2.Message) -> tuple[bytes, float]:
    """Serialize protobuf message, returning bytes and serialization time in ms."""
    start = time.perf_counter()
    payload = bytes(message)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return payload, elapsed_ms


def _build_metadata_headers(
    message_type: str,
    serialization_time_ms: float,
    user_headers: dict[str, str] | None,
) -> dict[str, str]:
    """Build complete headers including metadata."""
    headers: dict[str, str] = {
        "message_type": message_type,
        "serialization_time_ms": f"{serialization_time_ms:.3f}",
        "producer_timestamp": str(int(time.time() * 1000)),
    }
    if user_headers:
        headers |= user_headers
    return headers


@dataclass(frozen=True, slots=True)
class _PublishContext:
    """Context for building message metadata after publish."""

    topic: str
    key: str | None
    size_bytes: int
    serialization_time_ms: float
    start_time: float


class KafkaProducer:
    """Async Kafka producer using aiokafka with circuit breaker and transaction support."""

    __slots__ = ("_circuit_breaker", "_config", "_health_status", "_metrics", "_producer")

    def __init__(self, config: KafkaClientConfig, metrics: KafkaMetrics | None = None) -> None:
        """Initialize producer with configuration."""
        self._config = config
        self._metrics = metrics or get_kafka_metrics()
        self._producer: AIOKafkaProducer | None = None
        cb_config = config.producer.circuit_breaker or CircuitBreakerConfig()
        self._circuit_breaker = CircuitBreaker(cb_config)
        self._health_status = HealthStatus(healthy=False, details={}, last_check=0.0)

    async def __aenter__(self) -> Self:
        """Initialize producer as async context manager."""
        await self._initialize()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: types.TracebackType | None,
    ) -> None:
        """Cleanup producer resources."""
        await self._cleanup()

    async def _initialize(self) -> None:
        """Initialize the AIOKafkaProducer."""
        try:
            producer_config = get_aiokafka_producer_config(self._config)
            self._producer = AIOKafkaProducer(**producer_config)
            await self._producer.start()

            self._health_status = HealthStatus(
                healthy=True,
                details={
                    "initialized": True,
                    "transactional": self._config.producer.enable_transactions,
                },
                last_check=time.time(),
            )
            logger.info(
                "Kafka producer initialized",
                client_id=self._config.client_id,
                transactional=self._config.producer.enable_transactions,
            )
        except KafkaError as e:
            msg = "Failed to initialize Kafka producer"
            raise ProducerError(msg, details={"error": str(e)}) from e

    async def _cleanup(self) -> None:
        """Cleanup producer resources."""
        if self._producer is None:
            return
        try:
            await self._producer.stop()
            logger.info("Kafka producer cleaned up")
        except KafkaError as e:
            logger.warning("Error stopping producer during cleanup", error=str(e))
        finally:
            self._producer = None

    def _raise_not_initialized(self) -> NoReturn:
        """Raise error when producer is not initialized."""
        raise ProducerError(ERR_PRODUCER_NOT_INITIALIZED)

    def is_ready(self) -> bool:
        """Check if the producer is fully initialized and ready to use."""
        return self._producer is not None

    def _build_metadata(
        self,
        ctx: _PublishContext,
        partition: int,
        offset: int,
        timestamp: int | None,
    ) -> MessageMetadata:
        """Build MessageMetadata from publish result."""
        return MessageMetadata(
            topic=ctx.topic,
            partition=partition,
            offset=offset,
            timestamp=timestamp or 0,
            key=ctx.key,
            size_bytes=ctx.size_bytes,
            serialization_time_ms=ctx.serialization_time_ms,
            publish_time_ms=(time.perf_counter() - ctx.start_time) * 1000,
        )

    async def _send_message(
        self,
        topic: str,
        value: bytes,
        key: bytes | None,
        headers: list[tuple[str, bytes]] | None,
    ) -> tuple[int, int, int | None]:
        """Send a single message and return (partition, offset, timestamp)."""
        if self._producer is None:
            self._raise_not_initialized()

        record_metadata = await self._producer.send_and_wait(
            topic,
            value=value,
            key=key,
            headers=headers,
        )
        return record_metadata.partition, record_metadata.offset, record_metadata.timestamp

    async def publish(
        self,
        topic: str,
        message: betterproto2.Message,
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish a protobuf message with circuit breaker protection."""
        if self._producer is None:
            self._raise_not_initialized()

        start_time = time.perf_counter()
        payload, serialization_time = _serialize_protobuf(message)
        full_headers = _build_metadata_headers(
            type(message).__name__,
            serialization_time,
            headers,
        )
        encoded_headers = _encode_headers(full_headers)
        encoded_key = key.encode("utf-8") if key else None
        ctx = _PublishContext(
            topic=topic,
            key=key,
            size_bytes=len(payload),
            serialization_time_ms=serialization_time,
            start_time=start_time,
        )

        async def do_publish() -> MessageMetadata:
            partition, offset, timestamp = await self._send_message(topic, payload, encoded_key, encoded_headers)
            return self._build_metadata(ctx, partition, offset, timestamp)

        try:
            metadata = await self._circuit_breaker.execute(do_publish)
        except KafkaError, ProducerError, CircuitBreakerOpenError:
            self._metrics.record_message_produced(
                topic=topic,
                duration_seconds=time.perf_counter() - start_time,
                success=False,
            )
            raise
        else:
            self._metrics.record_message_produced(
                topic=topic,
                duration_seconds=time.perf_counter() - start_time,
                success=True,
                partition=metadata.partition,
            )
            return metadata

    async def publish_raw(
        self,
        topic: str,
        key: str | None,
        value: bytes,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish raw bytes with headers (used by DLQ system)."""
        if self._producer is None:
            self._raise_not_initialized()

        start_time = time.perf_counter()
        encoded_headers = _encode_headers(headers)
        encoded_key = key.encode("utf-8") if key else None

        ctx = _PublishContext(
            topic=topic,
            key=key,
            size_bytes=len(value),
            serialization_time_ms=0.0,
            start_time=start_time,
        )
        try:
            partition, offset, timestamp = await self._send_message(topic, value, encoded_key, encoded_headers)
        except KafkaError as e:
            self._metrics.record_message_produced(
                topic=topic,
                duration_seconds=time.perf_counter() - start_time,
                success=False,
            )
            msg = f"Failed to publish raw message to {topic}"
            raise ProducerError(msg, details={"error": str(e)}) from e
        else:
            metadata = self._build_metadata(ctx, partition, offset, timestamp)
            self._metrics.record_message_produced(
                topic=topic,
                duration_seconds=time.perf_counter() - start_time,
                success=True,
                partition=metadata.partition,
            )
            return metadata

    async def publish_json(
        self,
        topic: str,
        value: dict[str, object],
        key: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> MessageMetadata:
        """Publish JSON message for sink connectors."""
        try:
            json_bytes = json.dumps(value).encode("utf-8")
        except (TypeError, ValueError) as e:
            msg = f"Failed to serialize JSON for topic {topic}"
            raise ProducerError(msg, details={"error": str(e)}) from e
        return await self.publish_raw(topic=topic, key=key, value=json_bytes, headers=headers)

    async def publish_batch(self, topic: str, messages: list[ProducerMessage]) -> BatchResult:
        """Publish messages in a transaction."""
        if self._producer is None:
            self._raise_not_initialized()
        if not self._config.producer.enable_transactions:
            raise ProducerError(ERR_BATCH_REQUIRES_TRANSACTIONS)

        start_time = time.perf_counter()
        successful: list[MessageMetadata] = []
        errors: list[ProducerError] = []
        total_size = 0

        transaction = self.begin_transaction()
        async with transaction:
            for msg in messages:
                try:
                    metadata = await self.publish(
                        topic=topic,
                        message=msg.message,
                        key=msg.key,
                        headers=msg.headers,
                    )
                    successful.append(metadata)
                    total_size += metadata.size_bytes
                except ProducerError as e:
                    errors.append(e)
                    logger.warning(
                        "Batch message failed",
                        topic=topic,
                        message_type=type(msg.message).__name__,
                        error=str(e),
                    )
            if errors:
                await transaction.abort()

        return BatchResult(
            successful_count=len(successful),
            failed_count=len(errors),
            total_size_bytes=total_size,
            processing_time_ms=(time.perf_counter() - start_time) * 1000,
            metadata=successful,
            errors=errors,
        )

    def begin_transaction(self) -> Transaction:
        """Begin an explicit transaction."""
        if self._producer is None:
            raise ProducerError(ERR_PRODUCER_NOT_INITIALIZED)
        if not self._config.producer.enable_transactions:
            raise ProducerError(ERR_TRANSACTIONS_NOT_ENABLED)
        if not self._config.producer.transactional_id:
            raise ProducerError(ERR_TRANSACTIONAL_ID_REQUIRED)
        return Transaction(self._producer, self._config.producer.transactional_id)

    async def health_check(self) -> HealthStatus:
        """Check producer health."""
        if self._producer is None:
            return HealthStatus(
                healthy=False,
                details={"error": ERR_PRODUCER_NOT_INITIALIZED},
                last_check=time.time(),
            )
        try:
            partitions = await self._producer.partitions_for("__consumer_offsets")
            self._health_status = HealthStatus(
                healthy=True,
                details={
                    "partition_count": len(partitions) if partitions else 0,
                    "connected": True,
                },
                last_check=time.time(),
            )
        except KafkaError as e:
            self._health_status = HealthStatus(
                healthy=False,
                details={"error": str(e)},
                last_check=time.time(),
            )
        return self._health_status

    async def flush(self) -> None:
        """Flush pending messages."""
        if self._producer is not None:
            await self._producer.flush()

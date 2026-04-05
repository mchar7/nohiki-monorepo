"""Dead Letter Queue handler with non-blocking retry via Kafka retry topics.

Retry state (count, backoff, original topic) is tracked entirely in Kafka
message headers: no Redis or in-memory state required.  Failed messages
are published to ``{consumer_group}.retry`` with backoff metadata; a
dedicated ``RetryConsumer`` (see ``retry_consumer.py``) handles
reprocessing after the backoff period elapses.
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nohiki_observability import get_logger

from nohiki_kafka_client.config import GlobalDLQConfig
from nohiki_kafka_client.dlq.models import (
    ConsumedMessage,
    DLQMessage,
    DLQResult,
    ErrorInfo,
    ProcessingContext,
)
from nohiki_kafka_client.exceptions import DLQError, DLQPublishError
from nohiki_kafka_client.handlers import DLQStrategy, ErrorAction, ResilienceConfig, classify_error_action
from nohiki_kafka_client.observability.metrics import KafkaMetrics

if TYPE_CHECKING:
    from nohiki_kafka_client.producer import KafkaProducer

logger = get_logger(__name__)


class DLQHandler:
    """Non-blocking Dead Letter Queue system.

    Uses error classification to route failures to either a retry topic
    (transient errors) or a DLQ topic (permanent errors).  The main
    consumer never sleeps: retry backoff metadata is encoded in Kafka
    headers and applied by a dedicated ``RetryConsumer``.
    """

    def __init__(
        self,
        config: GlobalDLQConfig,
        metrics: KafkaMetrics,
        consumer_group: str = "",
    ) -> None:
        """Initialize DLQ handler.

        Args:
            config: Global DLQ configuration.
            metrics: Kafka metrics instance for recording DLQ events.
            consumer_group: Consumer group name, used to derive the
                retry topic (``{consumer_group}.retry``).

        """
        self._config = config
        self._metrics = metrics
        self._consumer_group = consumer_group
        self._producer: KafkaProducer | None = None

    def set_producer(self, producer: KafkaProducer) -> None:
        """Set the Kafka producer for republishing messages."""
        self._producer = producer

    def _build_error_info(self, error: Exception) -> ErrorInfo:
        """Build structured error info from an exception."""
        return ErrorInfo(
            error_type=type(error).__name__,
            error_message=str(error),
            error_stacktrace=traceback.format_exc(),
            timestamp=datetime.now(UTC),
        )

    def _resolve_max_retries(self, handler_resilience: ResilienceConfig | None) -> int:
        """Resolve effective max_retries from per-handler override or global config."""
        if handler_resilience is not None and handler_resilience.max_retries is not None:
            return handler_resilience.max_retries
        return self._config.max_retries

    def _resolve_retry_backoff_ms(self, handler_resilience: ResilienceConfig | None) -> int:
        """Resolve effective retry_backoff_ms from per-handler override or global config."""
        if handler_resilience is not None and handler_resilience.retry_backoff_ms is not None:
            return handler_resilience.retry_backoff_ms
        return self._config.retry_backoff_ms

    def _resolve_max_backoff_ms(self, handler_resilience: ResilienceConfig | None) -> int:
        """Resolve effective max_backoff_ms from per-handler override or global config."""
        if handler_resilience is not None and handler_resilience.max_backoff_ms is not None:
            return handler_resilience.max_backoff_ms
        return self._config.max_backoff_ms

    def _resolve_strategy(self, handler_resilience: ResilienceConfig | None) -> DLQStrategy:
        """Resolve effective DLQ strategy from per-handler override or global config."""
        if handler_resilience is not None and handler_resilience.strategy is not None:
            return handler_resilience.strategy
        return self._config.strategy

    async def handle_failure(
        self,
        original_message: ConsumedMessage,
        error: Exception,
        context: ProcessingContext,
        handler_resilience: ResilienceConfig | None = None,
    ) -> DLQResult:
        """Handle message processing failure.

        Classifies the error and routes to either the retry topic
        (transient) or the DLQ topic (permanent / max retries exceeded).

        Args:
            original_message: The consumed Kafka message that failed.
            error: The exception raised during processing.
            context: Processing context with consumer group and handler info.
            handler_resilience: Optional per-handler overrides for retry/DLQ
                behaviour.  Fields left as ``None`` fall back to global config.

        Returns:
            Result indicating success/failure and strategy used.

        """
        start_time = time.perf_counter()

        try:
            error_info = self._build_error_info(error)
            action = classify_error_action(error)
            retry_count = _get_retry_count_from_headers(original_message)
            max_retries = self._resolve_max_retries(handler_resilience)

            if action == ErrorAction.RETRY and retry_count < max_retries:
                result = await self._publish_to_retry_topic(
                    original_message,
                    error,
                    retry_count,
                    handler_resilience,
                )
            else:
                result = await self._send_to_dlq(
                    original_message,
                    error_info,
                    context,
                    retry_count,
                    handler_resilience,
                )

            self._metrics.record_dlq_message(
                topic=original_message.topic,
                consumer_group=context.consumer_group,
                reason=error_info.error_type,
            )

        except DLQPublishError:
            raise  # Must propagate to prevent silent data loss
        except Exception as dlq_error:
            processing_time = (time.perf_counter() - start_time) * 1000
            logger.exception(
                "DLQ processing failed",
                source_topic=original_message.topic,
                error_type=type(error).__name__,
                dlq_error=str(dlq_error),
                processing_time_ms=processing_time,
            )
            msg = "DLQ processing failed before durable routing"
            raise DLQPublishError(
                msg,
                details={
                    "original_error": str(dlq_error),
                    "processing_time_ms": processing_time,
                },
            ) from dlq_error
        else:
            return result

    async def _publish_to_retry_topic(
        self,
        original_message: ConsumedMessage,
        error: Exception,
        retry_count: int,
        handler_resilience: ResilienceConfig | None = None,
    ) -> DLQResult:
        """Publish failed message to retry topic with backoff metadata.

        The main consumer commits the original offset immediately: no
        semaphore slot is blocked.  The dedicated ``RetryConsumer``
        handles reprocessing after the backoff period.

        Args:
            original_message: The consumed Kafka message that failed.
            error: The exception raised during processing.
            retry_count: Current retry count (from headers).
            handler_resilience: Optional per-handler resilience overrides.

        Returns:
            DLQResult indicating success.

        Raises:
            DLQPublishError: If no producer is available or publish fails.

        """
        if not self._producer:
            msg = "Producer not available for retry publishing"
            raise DLQPublishError(msg)

        retry_backoff_ms = self._resolve_retry_backoff_ms(handler_resilience)
        max_backoff_ms = self._resolve_max_backoff_ms(handler_resilience)

        new_retry_count = retry_count + 1
        backoff_ms = min(
            retry_backoff_ms * (2 ** (retry_count)),
            max_backoff_ms,
        )
        next_retry_at = time.time() + (backoff_ms / 1000.0)

        first_failure_at = _get_header_value(original_message, "x-first-failure-at") or str(time.time())

        retry_headers = _strip_retry_headers(original_message.headers) | {
            "x-retry-count": str(new_retry_count),
            "x-next-retry-at": str(next_retry_at),
            "x-original-topic": original_message.topic,
            "x-error-type": type(error).__name__,
            "x-first-failure-at": first_failure_at,
        }

        retry_topic = f"{self._consumer_group}.retry"

        try:
            await self._producer.publish_raw(
                topic=retry_topic,
                key=original_message.key,
                value=original_message.raw_value,
                headers=retry_headers,
            )
        except Exception as publish_error:
            msg = f"Failed to publish to retry topic {retry_topic}"
            raise DLQPublishError(msg, details={"error": str(publish_error)}) from publish_error

        logger.info(
            "Message published to retry topic (non-blocking)",
            retry_topic=retry_topic,
            retry_count=new_retry_count,
            next_retry_at=next_retry_at,
            backoff_ms=backoff_ms,
        )
        return DLQResult(success=True, strategy_used=DLQStrategy.REPUBLISH)

    async def _send_to_dlq(
        self,
        original_message: ConsumedMessage,
        error_info: ErrorInfo,
        context: ProcessingContext,
        retry_count: int,
        handler_resilience: ResilienceConfig | None = None,
    ) -> DLQResult:
        """Send message to dead letter queue based on configured strategy."""
        strategy = self._resolve_strategy(handler_resilience)
        match strategy:
            case DLQStrategy.LOG_ONLY:
                return self._log_only_dlq(original_message, error_info, retry_count)
            case DLQStrategy.REPUBLISH:
                return await self._republish_dlq(
                    original_message,
                    error_info,
                    context,
                    retry_count,
                )
            case _:
                msg = f"Unknown DLQ strategy: {strategy}"
                raise DLQError(msg)

    @staticmethod
    def _log_only_dlq(
        original_message: ConsumedMessage,
        error_info: ErrorInfo,
        retry_count: int,
    ) -> DLQResult:
        """Handle DLQ by logging only."""
        logger.warning(
            "Message sent to dead letter queue (log-only)",
            source_topic=original_message.topic,
            dlq_topic="N/A (log-only)",
            error_info=error_info.error_message,
            retry_count=retry_count,
            strategy=DLQStrategy.LOG_ONLY.value,
        )
        return DLQResult(success=True, strategy_used=DLQStrategy.LOG_ONLY)

    async def _republish_dlq(
        self,
        original_message: ConsumedMessage,
        error_info: ErrorInfo,
        context: ProcessingContext,
        retry_count: int,
    ) -> DLQResult:
        """Republish message to DLQ topic."""
        if not self._producer:
            msg = "Producer not available for DLQ republishing"
            raise DLQPublishError(msg)

        dlq_topic = f"{self._config.topic_prefix}.{original_message.topic}"
        dlq_message = _build_dlq_message(
            original_message,
            error_info,
            context,
            retry_count,
        )

        try:
            dlq_payload = json.dumps(dlq_message.to_dict()).encode("utf-8")
            await self._producer.publish_raw(
                topic=dlq_topic,
                key=original_message.key,
                value=dlq_payload,
                headers=original_message.headers
                | {
                    "dlq-source-topic": original_message.topic,
                    "dlq-error-type": error_info.error_type,
                    "dlq-retry-count": str(retry_count),
                    "dlq-timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as republish_error:
            msg = f"Failed to republish to DLQ topic {dlq_topic}"
            raise DLQPublishError(msg, details={"error": str(republish_error)}) from republish_error

        logger.warning(
            "Message sent to dead letter queue (republish)",
            source_topic=original_message.topic,
            dlq_topic=dlq_topic,
            error_info=error_info.error_message,
            retry_count=retry_count,
            strategy=DLQStrategy.REPUBLISH.value,
        )
        return DLQResult(success=True, strategy_used=DLQStrategy.REPUBLISH, dlq_topic=dlq_topic)


# Header helpers (shared with retry_consumer.py)

_RETRY_HEADER_KEYS = frozenset(
    {
        "x-retry-count",
        "x-next-retry-at",
        "x-original-topic",
        "x-error-type",
        "x-first-failure-at",
    }
)


def _get_retry_count_from_headers(message: ConsumedMessage) -> int:
    """Extract retry count from message headers."""
    if value := message.headers.get("x-retry-count"):
        try:
            return int(value)
        except ValueError, TypeError:
            return 0
    return 0


def _get_header_value(message: ConsumedMessage, key: str) -> str | None:
    """Extract a single header value from a consumed message."""
    return message.headers.get(key)


def _strip_retry_headers(headers: dict[str, str]) -> dict[str, str]:
    """Remove existing retry headers before adding updated ones."""
    return {k: v for k, v in headers.items() if k not in _RETRY_HEADER_KEYS}


def _build_dlq_message(
    original_message: ConsumedMessage,
    error_info: ErrorInfo,
    context: ProcessingContext,
    retry_count: int,
) -> DLQMessage:
    """Construct the DLQMessage payload for republishing."""
    first_failure_at_str = _get_header_value(original_message, "x-first-failure-at")
    first_failure = (
        datetime.fromtimestamp(float(first_failure_at_str), tz=UTC) if first_failure_at_str else datetime.now(UTC)
    )
    return DLQMessage(
        source_topic=original_message.topic,
        original_partition=original_message.partition,
        original_offset=original_message.offset,
        original_timestamp=datetime.fromtimestamp(
            original_message.timestamp / 1000,
            tz=UTC,
        ),
        original_headers=original_message.headers,
        original_payload=original_message.raw_value,
        original_key=original_message.key,
        error_message=error_info.error_message,
        error_type=error_info.error_type,
        error_stacktrace=error_info.error_stacktrace,
        retry_count=retry_count,
        first_failure_timestamp=first_failure,
        last_failure_timestamp=datetime.now(UTC),
        processing_context=context.additional_metadata or {},
        consumer_group=context.consumer_group,
        handler_name=context.handler_name,
    )

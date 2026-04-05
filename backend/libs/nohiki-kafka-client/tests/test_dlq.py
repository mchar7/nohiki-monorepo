"""Unit tests for Dead Letter Queue module."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_kafka_client.config import GlobalDLQConfig
from nohiki_kafka_client.dlq import (
    ConsumedMessage,
    DLQHandler,
    DLQMessage,
    DLQResult,
    ErrorInfo,
    ProcessingContext,
)
from nohiki_kafka_client.dlq.handler import (
    _build_dlq_message,
    _get_retry_count_from_headers,
    _strip_retry_headers,
)
from nohiki_kafka_client.exceptions import DLQPublishError
from nohiki_kafka_client.handlers import DLQStrategy


class TestErrorInfo:
    """Tests for ErrorInfo dataclass."""

    def test_create_error_info(self) -> None:
        """ErrorInfo stores all fields."""
        now = datetime.now(UTC)
        info = ErrorInfo(
            error_type="ValueError",
            error_message="Invalid value",
            error_stacktrace="Traceback...",
            timestamp=now,
        )
        assert info.error_type == "ValueError"
        assert info.error_message == "Invalid value"
        assert info.error_stacktrace == "Traceback..."
        assert info.timestamp == now


class TestConsumedMessage:
    """Tests for ConsumedMessage dataclass."""

    def test_create_consumed_message(self) -> None:
        """ConsumedMessage stores all fields."""
        message = ConsumedMessage(
            topic="test-topic",
            partition=1,
            offset=100,
            timestamp=1234567890000,
            headers={"key": "value"},
            key="msg-key",
            raw_value=b"payload",
        )
        assert message.topic == "test-topic"
        assert message.partition == 1
        assert message.offset == 100
        assert message.timestamp == 1234567890000
        assert message.headers == {"key": "value"}
        assert message.key == "msg-key"
        assert message.raw_value == b"payload"


class TestProcessingContext:
    """Tests for ProcessingContext dataclass."""

    def test_create_processing_context(self) -> None:
        """ProcessingContext stores all fields."""
        ctx = ProcessingContext(
            consumer_group="test-group",
            handler_name="TestHandler",
            processing_start_time=time.time(),
            correlation_id="corr-123",
        )
        assert ctx.consumer_group == "test-group"
        assert ctx.handler_name == "TestHandler"
        assert ctx.correlation_id == "corr-123"

    def test_processing_context_initializes_metadata(self) -> None:
        """ProcessingContext initializes additional_metadata if None."""
        ctx = ProcessingContext(
            consumer_group="group",
            handler_name="handler",
            processing_start_time=time.time(),
        )
        assert ctx.additional_metadata == {}

    def test_processing_context_preserves_metadata(self) -> None:
        """ProcessingContext preserves provided metadata."""
        metadata: dict[str, object] = {"key": "value"}
        ctx = ProcessingContext(
            consumer_group="group",
            handler_name="handler",
            processing_start_time=time.time(),
            additional_metadata=metadata,
        )
        assert ctx.additional_metadata == {"key": "value"}


class TestDLQMessage:
    """Tests for DLQMessage dataclass."""

    def test_create_dlq_message(self) -> None:
        """DLQMessage stores all fields."""
        now = datetime.now(UTC)
        msg = DLQMessage(
            source_topic="source",
            original_partition=0,
            original_offset=100,
            original_timestamp=now,
            original_headers={"h": "v"},
            original_payload=b"data",
            original_key="key",
            error_message="Failed",
            error_type="ValueError",
            error_stacktrace="Traceback",
            retry_count=3,
            first_failure_timestamp=now,
            last_failure_timestamp=now,
            processing_context={"ctx": "val"},
            consumer_group="group",
            handler_name="handler",
        )
        assert msg.source_topic == "source"
        assert msg.retry_count == 3

    def test_to_dict(self) -> None:
        """to_dict converts DLQMessage to dictionary."""
        now = datetime.now(UTC)
        msg = DLQMessage(
            source_topic="source",
            original_partition=0,
            original_offset=100,
            original_timestamp=now,
            original_headers={},
            original_payload=b"\x00\x01\x02",
            original_key=None,
            error_message="error",
            error_type="Error",
            error_stacktrace="trace",
            retry_count=1,
            first_failure_timestamp=now,
            last_failure_timestamp=now,
            processing_context={},
            consumer_group="group",
            handler_name="handler",
        )
        result = msg.to_dict()
        assert result["source_topic"] == "source"
        assert result["original_offset"] == 100
        assert result["original_payload"] == "000102"  # hex encoded
        assert result["retry_count"] == 1


class TestDLQResult:
    """Tests for DLQResult dataclass."""

    def test_create_success_result(self) -> None:
        """DLQResult can represent success."""
        result = DLQResult(success=True, strategy_used=DLQStrategy.REPUBLISH)
        assert result.success is True
        assert result.strategy_used == DLQStrategy.REPUBLISH
        assert result.error is None

    def test_create_failure_result(self) -> None:
        """DLQResult can represent failure."""
        error = ValueError("Failed")
        result = DLQResult(success=False, strategy_used=DLQStrategy.LOG_ONLY, error=error)
        assert result.success is False
        assert result.error == error


class TestRetryHeaderHelpers:
    """Tests for header-based retry state helpers."""

    def test_get_retry_count_from_headers_default(self) -> None:
        """Returns 0 when no retry header present."""
        msg = ConsumedMessage(
            topic="t",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"",
        )
        assert _get_retry_count_from_headers(msg) == 0

    def test_get_retry_count_from_headers_valid(self) -> None:
        """Parses integer retry count from header."""
        msg = ConsumedMessage(
            topic="t",
            partition=0,
            offset=0,
            timestamp=0,
            headers={"x-retry-count": "3"},
            key=None,
            raw_value=b"",
        )
        assert _get_retry_count_from_headers(msg) == 3

    def test_get_retry_count_from_headers_invalid(self) -> None:
        """Returns 0 for non-integer retry count."""
        msg = ConsumedMessage(
            topic="t",
            partition=0,
            offset=0,
            timestamp=0,
            headers={"x-retry-count": "bad"},
            key=None,
            raw_value=b"",
        )
        assert _get_retry_count_from_headers(msg) == 0

    def test_strip_retry_headers(self) -> None:
        """Strips only retry-related headers."""
        headers = {
            "x-retry-count": "2",
            "x-next-retry-at": "123.0",
            "x-original-topic": "foo",
            "x-error-type": "ValueError",
            "x-first-failure-at": "100.0",
            "keep-this": "yes",
        }
        result = _strip_retry_headers(headers)
        assert result == {"keep-this": "yes"}

    def test_build_dlq_message_with_first_failure_header(self) -> None:
        """DLQ message uses x-first-failure-at header when present."""
        now = datetime.now(UTC)
        msg = ConsumedMessage(
            topic="src",
            partition=0,
            offset=10,
            timestamp=1000,
            headers={"x-first-failure-at": str(now.timestamp())},
            key="k",
            raw_value=b"data",
        )
        error_info = ErrorInfo(
            error_type="ValueError",
            error_message="err",
            error_stacktrace="trace",
            timestamp=now,
        )
        ctx = ProcessingContext(
            consumer_group="g",
            handler_name="h",
            processing_start_time=time.time(),
        )
        dlq_msg = _build_dlq_message(msg, error_info, ctx, retry_count=2)
        assert dlq_msg.retry_count == 2
        assert dlq_msg.source_topic == "src"


class TestDLQHandler:
    """Tests for DLQHandler."""

    @pytest.fixture
    def mock_config(self) -> GlobalDLQConfig:
        """Create mock DLQ config."""
        return GlobalDLQConfig(
            strategy=DLQStrategy.LOG_ONLY,
            max_retries=3,
        )

    @pytest.fixture
    def mock_metrics(self) -> MagicMock:
        """Create mock KafkaMetrics."""
        metrics = MagicMock()
        metrics.record_dlq_message = MagicMock()
        return metrics

    def test_init_creates_handler(self, mock_config: GlobalDLQConfig, mock_metrics: MagicMock) -> None:
        """DLQHandler initializes with config, metrics, and consumer_group."""
        handler = DLQHandler(mock_config, mock_metrics, consumer_group="test-group")
        assert handler._config == mock_config
        assert handler._producer is None
        assert handler._consumer_group == "test-group"

    def test_set_producer(self, mock_config: GlobalDLQConfig, mock_metrics: MagicMock) -> None:
        """set_producer sets the producer instance."""
        handler = DLQHandler(mock_config, mock_metrics)
        mock_producer = MagicMock()
        handler.set_producer(mock_producer)
        assert handler._producer == mock_producer

    @pytest.mark.asyncio
    async def test_handle_failure_retryable_publishes_to_retry_topic(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Transient errors publish to retry topic when under max_retries."""
        config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=3)
        handler = DLQHandler(config, mock_metrics, consumer_group="my-group")

        mock_producer = MagicMock()
        mock_producer.publish_raw = AsyncMock()
        handler.set_producer(mock_producer)

        message = ConsumedMessage(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="my-group",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        result = await handler.handle_failure(message, OSError("transient"), context)

        assert result.success is True
        assert result.strategy_used == DLQStrategy.REPUBLISH
        mock_producer.publish_raw.assert_awaited_once()
        call_kwargs = mock_producer.publish_raw.call_args
        assert call_kwargs.kwargs["topic"] == "my-group.retry"

    @pytest.mark.asyncio
    async def test_handle_failure_permanent_error_sends_to_dlq(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Non-retryable errors go straight to DLQ (log_only)."""
        config = GlobalDLQConfig(strategy=DLQStrategy.LOG_ONLY, max_retries=3)
        handler = DLQHandler(config, mock_metrics, consumer_group="g")

        message = ConsumedMessage(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        result = await handler.handle_failure(message, ValueError("bad data"), context)

        assert result.success is True
        assert result.strategy_used == DLQStrategy.LOG_ONLY

    @pytest.mark.asyncio
    async def test_handle_failure_retryable_exceeds_max_retries_sends_to_dlq(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Retryable error that exceeds max_retries goes to DLQ."""
        config = GlobalDLQConfig(strategy=DLQStrategy.LOG_ONLY, max_retries=2)
        handler = DLQHandler(config, mock_metrics, consumer_group="g")

        message = ConsumedMessage(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={"x-retry-count": "3"},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        result = await handler.handle_failure(message, OSError("transient"), context)

        assert result.success is True
        assert result.strategy_used == DLQStrategy.LOG_ONLY

    @pytest.mark.asyncio
    async def test_handle_failure_dlq_processing_error(
        self,
        mock_config: GlobalDLQConfig,
        mock_metrics: MagicMock,
    ) -> None:
        """handle_failure returns failure result when DLQ processing itself fails."""
        handler = DLQHandler(mock_config, mock_metrics, consumer_group="g")

        message = ConsumedMessage(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        result = await handler.handle_failure(message, ValueError("orig"), context)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_republish_strategy_sends_to_dlq_topic(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Republish strategy publishes message to DLQ topic via producer."""
        config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=0, topic_prefix="dlq")
        handler = DLQHandler(config, mock_metrics, consumer_group="g")

        mock_producer = MagicMock()
        mock_producer.publish_raw = AsyncMock()
        handler.set_producer(mock_producer)

        message = ConsumedMessage(
            topic="test-topic",
            partition=0,
            offset=0,
            timestamp=1000,
            headers={},
            key="k",
            raw_value=b"val",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        result = await handler.handle_failure(message, ValueError("err"), context)

        assert result.success is True
        assert result.strategy_used == DLQStrategy.REPUBLISH
        assert result.dlq_topic == "dlq.test-topic"
        mock_producer.publish_raw.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_republish_without_producer_returns_failure(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Republish strategy returns failure when no producer is set."""
        config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=0)
        handler = DLQHandler(config, mock_metrics, consumer_group="g")

        message = ConsumedMessage(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        with pytest.raises(DLQPublishError):
            await handler.handle_failure(message, ValueError("err"), context)

    @pytest.mark.asyncio
    async def test_republish_publish_failure_returns_error(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Republish strategy returns error when publish_raw fails."""
        config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=0, topic_prefix="dlq")
        handler = DLQHandler(config, mock_metrics, consumer_group="g")

        mock_producer = MagicMock()
        mock_producer.publish_raw = AsyncMock(side_effect=RuntimeError("network error"))
        handler.set_producer(mock_producer)

        message = ConsumedMessage(
            topic="topic",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="handler",
            processing_start_time=time.time(),
        )

        with pytest.raises(DLQPublishError):
            await handler.handle_failure(message, ValueError("err"), context)

    @pytest.mark.asyncio
    async def test_retry_headers_set_correctly(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Retry topic publish includes correct backoff headers."""
        config = GlobalDLQConfig(
            strategy=DLQStrategy.REPUBLISH,
            max_retries=5,
            retry_backoff_ms=1000,
            max_backoff_ms=30000,
        )
        handler = DLQHandler(config, mock_metrics, consumer_group="svc-group")

        mock_producer = MagicMock()
        mock_producer.publish_raw = AsyncMock()
        handler.set_producer(mock_producer)

        message = ConsumedMessage(
            topic="t",
            partition=0,
            offset=0,
            timestamp=0,
            headers={"x-retry-count": "1"},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="svc-group",
            handler_name="h",
            processing_start_time=time.time(),
        )

        await handler.handle_failure(message, OSError("net"), context)

        call_kwargs = mock_producer.publish_raw.call_args.kwargs
        headers = call_kwargs["headers"]
        assert headers["x-retry-count"] == "2"
        assert "x-next-retry-at" in headers
        assert headers["x-original-topic"] == "t"
        assert headers["x-error-type"] == "OSError"
        assert "x-first-failure-at" in headers

    @pytest.mark.asyncio
    async def test_retry_without_producer_returns_failure(
        self,
        mock_metrics: MagicMock,
    ) -> None:
        """Retry publish returns failure when no producer is available."""
        config = GlobalDLQConfig(strategy=DLQStrategy.REPUBLISH, max_retries=5)
        handler = DLQHandler(config, mock_metrics, consumer_group="g")

        message = ConsumedMessage(
            topic="t",
            partition=0,
            offset=0,
            timestamp=0,
            headers={},
            key=None,
            raw_value=b"data",
        )
        context = ProcessingContext(
            consumer_group="g",
            handler_name="h",
            processing_start_time=time.time(),
        )

        with pytest.raises(DLQPublishError):
            await handler.handle_failure(message, OSError("net"), context)

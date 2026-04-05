"""Tests for Kafka trace context propagation."""

from __future__ import annotations

from nohiki_kafka_client.observability.tracing import (
    ConsumerSpanParams,
    KafkaHeaderCarrier,
    create_consumer_span,
    create_producer_span,
    end_span_error,
    end_span_ok,
    extract_trace_context,
    get_span_id_from_context,
    get_trace_id_from_context,
    inject_trace_context,
)
from opentelemetry import trace


class TestKafkaHeaderCarrier:
    """Tests for KafkaHeaderCarrier."""

    def test_init_empty(self) -> None:
        """Test initialization with no headers."""
        carrier = KafkaHeaderCarrier()
        assert len(carrier) == 0

    def test_init_with_headers(self) -> None:
        """Test initialization with existing headers."""
        headers = {"key1": "value1", "key2": "value2"}
        carrier = KafkaHeaderCarrier(headers)
        assert len(carrier) == 2
        assert carrier["key1"] == "value1"

    def test_setitem_getitem(self) -> None:
        """Test setting and getting items."""
        carrier = KafkaHeaderCarrier()
        carrier["test-key"] = "test-value"
        assert carrier["test-key"] == "test-value"

    def test_delitem(self) -> None:
        """Test deleting items."""
        carrier = KafkaHeaderCarrier({"key": "value"})
        del carrier["key"]
        assert len(carrier) == 0

    def test_iter(self) -> None:
        """Test iteration over keys."""
        headers = {"a": "1", "b": "2"}
        carrier = KafkaHeaderCarrier(headers)
        assert sorted(carrier) == ["a", "b"]

    def test_to_dict(self) -> None:
        """Test converting to dict."""
        headers = {"key": "value"}
        carrier = KafkaHeaderCarrier(headers)
        result = carrier.to_dict()
        assert result == headers
        # Ensure it's a copy
        result["new"] = "item"
        assert "new" not in carrier


class TestTraceContextPropagation:
    """Tests for trace context injection and extraction."""

    def test_inject_extract_roundtrip(self) -> None:
        """Test that inject/extract preserves trace context."""
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("test-span") as span:
            # Get original trace info
            original_ctx = span.get_span_context()
            original_trace_id = format(original_ctx.trace_id, "032x")

            # Inject into headers
            headers: dict[str, str] = {}
            inject_trace_context(headers)

            # Verify traceparent header was set
            assert "traceparent" in headers

            # Extract from headers
            extracted_ctx = extract_trace_context(headers)

            # Verify trace ID is preserved
            extracted_trace_id = get_trace_id_from_context(extracted_ctx)
            assert extracted_trace_id == original_trace_id

    def test_extract_empty_headers(self) -> None:
        """Test extraction with empty headers returns current context."""
        ctx = extract_trace_context(None)
        assert ctx is not None

        ctx2 = extract_trace_context({})
        assert ctx2 is not None

    def test_get_trace_id_no_span(self) -> None:
        """Test get_trace_id_from_context with no active span."""
        # Clear any existing span context
        result = get_trace_id_from_context()
        # May be None or a valid trace ID depending on context
        assert result is None or len(result) == 32

    def test_get_span_id_no_span(self) -> None:
        """Test get_span_id_from_context with no active span."""
        result = get_span_id_from_context()
        assert result is None or len(result) == 16


class TestStandaloneFunctions:
    """Tests for standalone tracing functions (previously TracingMixin methods)."""

    def test_inject_trace_context_function(self) -> None:
        """Test standalone inject_trace_context."""
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("test"):
            headers: dict[str, str] = {}
            inject_trace_context(headers)
            assert "traceparent" in headers

    def test_extract_trace_context_function(self) -> None:
        """Test standalone extract_trace_context."""
        headers = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
        ctx = extract_trace_context(headers)
        assert ctx is not None

    def test_create_producer_span_function(self) -> None:
        """Test standalone create_producer_span."""
        span = create_producer_span(
            topic="test-topic",
            message_type="TestMessage",
            key="test-key",
        )

        assert span is not None
        span.end()

    def test_create_consumer_span_function(self) -> None:
        """Test standalone create_consumer_span."""
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("producer"):
            headers: dict[str, str] = {}
            inject_trace_context(headers)

        parent_ctx = extract_trace_context(headers)

        params = ConsumerSpanParams(
            parent_context=parent_ctx,
            topic="test-topic",
            partition=0,
            offset=100,
            message_type="TestMessage",
            consumer_group="test-group",
        )
        span = create_consumer_span(params)

        assert span is not None
        span.end()

    def test_end_span_ok_function(self) -> None:
        """Test standalone end_span_ok."""
        span = create_producer_span("topic", "Type")
        end_span_ok(span)

    def test_end_span_error_function(self) -> None:
        """Test standalone end_span_error."""
        span = create_producer_span("topic", "Type")
        error = ValueError("test error")
        end_span_error(span, error)

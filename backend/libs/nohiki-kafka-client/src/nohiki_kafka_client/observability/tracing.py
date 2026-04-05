"""W3C TraceContext propagation for Kafka messages.

Trace context injection and extraction for Kafka messages,
enabling distributed tracing across event-driven flows. Uses W3C TraceContext
standard for interoperability with OpenTelemetry and other tracing systems.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.context import Context, get_current
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, Status, StatusCode

# W3C TraceContext header names
TRACEPARENT_HEADER = "traceparent"
TRACESTATE_HEADER = "tracestate"

# Kafka header prefix for trace context
TRACE_HEADER_PREFIX = "trace."

_tracer = trace.get_tracer(__name__)


class KafkaHeaderCarrier(MutableMapping[str, str]):
    """Carrier adapter for Kafka message headers.

    Implements MutableMapping to allow OpenTelemetry propagators to inject
    and extract trace context from Kafka message headers.
    """

    __slots__ = ("_headers",)

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        """Initialize carrier with optional existing headers.

        Args:
            headers: Existing headers dict to wrap. Creates new dict if None.

        """
        self._headers: dict[str, str] = headers if headers is not None else {}

    def __getitem__(self, key: str) -> str:
        """Get header value by key."""
        return self._headers[key]

    def __setitem__(self, key: str, value: str) -> None:
        """Set header value."""
        self._headers[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete header by key."""
        del self._headers[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate over header keys."""
        return iter(self._headers)

    def __len__(self) -> int:
        """Return number of headers."""
        return len(self._headers)

    def to_dict(self) -> dict[str, str]:
        """Return headers as dict."""
        return self._headers.copy()


@dataclass(frozen=True, slots=True)
class ConsumerSpanParams:
    """Parameters for creating a consumer span."""

    parent_context: Context
    topic: str
    partition: int
    offset: int
    message_type: str
    consumer_group: str | None = None


def create_producer_span(
    topic: str,
    message_type: str,
    key: str | None = None,
) -> trace.Span:
    """Create a producer span for message publishing.

    The span is created with PRODUCER kind and includes standard
    messaging attributes per OpenTelemetry semantic conventions.

    Args:
        topic: Kafka topic name.
        message_type: Protobuf message type name.
        key: Optional message key.

    Returns:
        OpenTelemetry Span for the publish operation.

    """
    span = _tracer.start_span(
        name=f"{topic} publish",
        kind=SpanKind.PRODUCER,
    )

    span.set_attribute("messaging.system", "kafka")
    span.set_attribute("messaging.destination.name", topic)
    span.set_attribute("messaging.operation", "publish")
    span.set_attribute("messaging.message.type", message_type)

    if key:
        span.set_attribute("messaging.kafka.message.key", key)

    return span


def create_consumer_span(params: ConsumerSpanParams) -> trace.Span:
    """Create a consumer span linked to the producer span.

    The span is created with CONSUMER kind and linked to the parent
    context extracted from message headers. Includes standard messaging
    attributes per OpenTelemetry semantic conventions.

    Args:
        params: Parameters for span creation.

    Returns:
        OpenTelemetry Span for the consume operation.

    """
    span = _tracer.start_span(
        name=f"{params.topic} process",
        context=params.parent_context,
        kind=SpanKind.CONSUMER,
    )

    span.set_attribute("messaging.system", "kafka")
    span.set_attribute("messaging.source.name", params.topic)
    span.set_attribute("messaging.operation", "process")
    span.set_attribute("messaging.kafka.partition", params.partition)
    span.set_attribute("messaging.kafka.offset", params.offset)
    span.set_attribute("messaging.message.type", params.message_type)

    if params.consumer_group:
        span.set_attribute("messaging.kafka.consumer.group", params.consumer_group)

    return span


def end_span_ok(span: trace.Span) -> None:
    """End span with OK status.

    Args:
        span: Span to end.

    """
    span.set_status(Status(StatusCode.OK))
    span.end()


def end_span_error(span: trace.Span, error: Exception) -> None:
    """End span with ERROR status and record exception.

    Args:
        span: Span to end.
        error: Exception that caused the error.

    """
    span.set_status(Status(StatusCode.ERROR, str(error)))
    span.record_exception(error)
    span.end()


def inject_trace_context(headers: dict[str, str]) -> None:
    """Inject current trace context into headers dict.

    Convenience function for injecting trace context into Kafka message headers.

    Args:
        headers: Mutable dict to inject trace context into.

    """
    carrier = KafkaHeaderCarrier(headers)
    inject(carrier)


def extract_trace_context(headers: dict[str, str] | None) -> Context:
    """Extract trace context from headers dict.

    Convenience function for extracting trace context from Kafka message headers.

    Args:
        headers: Headers dict containing trace context.

    Returns:
        OpenTelemetry Context with extracted trace information.

    """
    if not headers:
        return get_current()

    carrier = KafkaHeaderCarrier(headers)
    return extract(carrier)


def get_trace_id_from_context(context: Context | None = None) -> str | None:
    """Get trace ID from context as hex string.

    Args:
        context: Optional context to extract from. Uses current if None.

    Returns:
        Trace ID as 32-character hex string, or None if no valid trace.

    """
    ctx = context or get_current()
    span = trace.get_current_span(ctx)

    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().trace_id, "032x")

    return None


def get_span_id_from_context(context: Context | None = None) -> str | None:
    """Get span ID from context as hex string.

    Args:
        context: Optional context to extract from. Uses current if None.

    Returns:
        Span ID as 16-character hex string, or None if no valid span.

    """
    ctx = context or get_current()
    span = trace.get_current_span(ctx)

    if span and span.get_span_context().is_valid:
        return format(span.get_span_context().span_id, "016x")

    return None

"""Observability: metrics, tracing, and health probes for Kafka operations."""

from .health import KafkaCapability, KafkaHealthProbe
from .instrumentation import maybe_enable_otel
from .metrics import KafkaMetrics, get_kafka_metrics
from .tracing import (
    ConsumerSpanParams,
    create_consumer_span,
    create_producer_span,
    end_span_error,
    end_span_ok,
    extract_trace_context,
    get_span_id_from_context,
    get_trace_id_from_context,
    inject_trace_context,
)

__all__ = [
    "ConsumerSpanParams",
    "KafkaCapability",
    "KafkaHealthProbe",
    "KafkaMetrics",
    "create_consumer_span",
    "create_producer_span",
    "end_span_error",
    "end_span_ok",
    "extract_trace_context",
    "get_kafka_metrics",
    "get_span_id_from_context",
    "get_trace_id_from_context",
    "inject_trace_context",
    "maybe_enable_otel",
]

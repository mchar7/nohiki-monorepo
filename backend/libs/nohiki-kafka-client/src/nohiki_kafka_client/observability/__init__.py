"""Observability: metrics, tracing, and health probes for Kafka operations."""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .health import KafkaCapability as KafkaCapability
    from .health import KafkaHealthProbe as KafkaHealthProbe
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

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "KafkaCapability": ("nohiki_kafka_client.observability.health", "KafkaCapability"),
    "KafkaHealthProbe": ("nohiki_kafka_client.observability.health", "KafkaHealthProbe"),
}


def __getattr__(name: str) -> object:
    """Resolve FastAPI health-probe exports on first use."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


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

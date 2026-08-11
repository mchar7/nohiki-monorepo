"""Shared pytest fixtures for nohiki-kafka-client tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import propagate as otel_propagate
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


@pytest.fixture
def configure_otel_test_provider(
    monkeypatch: pytest.MonkeyPatch,
    otel_exporter: InMemorySpanExporter,
) -> Iterator[None]:
    """Install restoring OpenTelemetry globals for one test."""
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    provider = TracerProvider(sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(otel_exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    monkeypatch.setattr(
        otel_propagate,
        "_HTTP_TEXT_FORMAT",
        TraceContextTextMapPropagator(),
    )
    yield
    provider.shutdown()


@pytest.fixture
def otel_exporter() -> InMemorySpanExporter:
    """Provide the OpenTelemetry exporter for a test."""
    return InMemorySpanExporter()


@pytest.fixture(autouse=True)
def reset_auto_kafka_client() -> Iterator[None]:
    """Restore the AutoKafkaClient singleton after each test."""
    import nohiki_kafka_client.client.auto_client as auto_client_module
    from nohiki_kafka_client.observability.metrics import get_kafka_metrics
    from nohiki_kafka_client.utils.callback_state import _get_valid_field_names

    get_kafka_metrics.cache_clear()
    _get_valid_field_names.cache_clear()
    previous = auto_client_module._global_instance[0]
    auto_client_module._global_instance[0] = None
    try:
        yield
    finally:
        auto_client_module._global_instance[0] = previous
        get_kafka_metrics.cache_clear()
        _get_valid_field_names.cache_clear()


__all__ = [
    "otel_exporter",
    "reset_auto_kafka_client",
]

"""Pytest configuration for nohiki-kafka-client tests.

Safety mechanism: Tests marked ``requires_docker`` are automatically deselected
unless ``--run-docker`` is passed on the command line.  This prevents accidental
Kafka testcontainer startup (heavy JVM process) during normal unit test runs.
"""

from __future__ import annotations

import os

import pytest
from opentelemetry import trace
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

os.environ.pop("OTEL_SDK_DISABLED", None)

_exporter = InMemorySpanExporter()
_provider = TracerProvider(sampler=ALWAYS_ON)
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)
set_global_textmap(TraceContextTextMapPropagator())


# Docker safety gate: auto-deselect requires_docker tests by default


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--run-docker`` CLI flag."""
    parser.addoption(
        "--run-docker",
        action="store_true",
        default=False,
        help="Run tests marked 'requires_docker' (starts real Kafka container).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect ``requires_docker`` tests unless ``--run-docker`` was passed."""
    if config.getoption("--run-docker", default=False):
        return

    docker_marker = pytest.mark.requires_docker
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []

    for item in items:
        if item.get_closest_marker(docker_marker.name):
            deselected.append(item)
        else:
            selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


@pytest.fixture(scope="session")
def otel_exporter() -> InMemorySpanExporter:
    """Provide the OpenTelemetry exporter for tests."""
    return _exporter


@pytest.fixture(autouse=True)
def reset_auto_kafka_client() -> None:
    """Reset AutoKafkaClient singleton before each test to ensure test isolation."""
    import nohiki_kafka_client.client.auto_client as auto_client_module

    auto_client_module._global_instance[0] = None


__all__ = [
    "otel_exporter",
    "pytest_addoption",
    "pytest_collection_modifyitems",
    "reset_auto_kafka_client",
]

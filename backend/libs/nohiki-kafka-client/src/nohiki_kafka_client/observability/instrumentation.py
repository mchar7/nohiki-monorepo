"""OpenTelemetry instrumentation for Kafka client."""

from __future__ import annotations

import importlib.util
from typing import Protocol

from nohiki_observability import get_logger

logger = get_logger(__name__)


class ConfluentKafkaInstrumentorProtocol(Protocol):
    """Protocol for ConfluentKafkaInstrumentor to satisfy type checker."""

    def instrument(self) -> None:
        """Instrument Kafka client with OpenTelemetry."""
        ...


def _is_otel_kafka_available() -> bool:
    """Check if OpenTelemetry Kafka instrumentation is available."""
    return importlib.util.find_spec("opentelemetry.instrumentation.aiokafka") is not None


def maybe_enable_otel(*, enabled: bool) -> None:
    """Enable OpenTelemetry Kafka instrumentation if configured and available."""
    if not enabled:
        return

    if not _is_otel_kafka_available():
        logger.debug("Kafka OpenTelemetry instrumentation not available - install nohiki-kafka-client[otel]")
        return

    try:
        otel_kafka = importlib.import_module("opentelemetry.instrumentation.aiokafka")
        instrumentor_cls = otel_kafka.AIOKafkaInstrumentor
        instrumentor: ConfluentKafkaInstrumentorProtocol = instrumentor_cls()
        instrumentor.instrument()
        logger.info("Kafka OpenTelemetry instrumentation enabled")

    except Exception as e:
        logger.exception("Failed to enable Kafka OpenTelemetry instrumentation")
        logger.warning("Instrumentation failure skipped to prevent app crash", error=str(e))

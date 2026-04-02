"""Outbox write metrics."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from opentelemetry import metrics


class OutboxMetrics:
    """Metrics for transactional outbox writes."""

    def __init__(self) -> None:
        """Initialize outbox metrics with OpenTelemetry meter."""
        self._meter = metrics.get_meter("nohiki.outbox")

        self.writes = self._meter.create_counter(
            "nohiki_outbox_writes_total",
            description="Total events written to outbox",
            unit="1",
        )
        self.write_duration = self._meter.create_histogram(
            "nohiki_outbox_write_duration_seconds",
            description="Outbox write latency",
            unit="s",
        )
        self.payload_size = self._meter.create_histogram(
            "nohiki_outbox_payload_bytes",
            description="Serialized event payload size",
            unit="By",
        )
        self.errors = self._meter.create_counter(
            "nohiki_outbox_errors_total",
            description="Outbox write errors",
            unit="1",
        )

    def record_write(
        self,
        event_type: str,
        aggregate_type: str,
        duration_seconds: float,
        payload_bytes: int,
    ) -> None:
        """Record a successful outbox write.

        Args:
            event_type: Kafka topic name for the event.
            aggregate_type: Type of aggregate (e.g., "job", "profile").
            duration_seconds: Time taken to write the event.
            payload_bytes: Size of the serialized payload.

        """
        attrs = {"event_type": event_type, "aggregate_type": aggregate_type}
        self.writes.add(1, attrs)
        self.write_duration.record(duration_seconds, attrs)
        self.payload_size.record(payload_bytes, attrs)

    def record_batch_write(
        self,
        event_type: str,
        aggregate_type: str,
        duration_seconds: float,
        payload_bytes: Sequence[int],
    ) -> None:
        """Record a successful batched outbox write.

        Args:
            event_type: Kafka topic name for the events.
            aggregate_type: Type of aggregate (e.g., "job", "profile").
            duration_seconds: Time taken to write the batch.
            payload_bytes: Serialized payload sizes for the batch.

        """
        attrs = {"event_type": event_type, "aggregate_type": aggregate_type}
        self.writes.add(len(payload_bytes), attrs)
        self.write_duration.record(duration_seconds, attrs)
        for size in payload_bytes:
            self.payload_size.record(size, attrs)

    def record_error(self, event_type: str, error_type: str) -> None:
        """Record an outbox write error.

        Args:
            event_type: Kafka topic name for the event that failed.
            error_type: Exception class name.

        """
        self.errors.add(1, {"event_type": event_type, "error_type": error_type})


@lru_cache(maxsize=1)
def get_outbox_metrics() -> OutboxMetrics:
    """Get singleton OutboxMetrics instance."""
    return OutboxMetrics()

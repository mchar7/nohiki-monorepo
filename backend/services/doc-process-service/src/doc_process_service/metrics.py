"""OpenTelemetry metrics for doc-process-service."""

from __future__ import annotations

from typing import ClassVar

from nohiki_observability.metrics import DomainMetricsBase, MetricDefinition


class DocProcessMetrics(DomainMetricsBase):
    """Document processing metrics using OpenTelemetry."""

    _instance: ClassVar[DocProcessMetrics | None] = None

    DEFINITIONS: ClassVar[list[MetricDefinition]] = [
        MetricDefinition(
            name="doc_process_requests_total",
            description="Total document processing requests",
            unit="1",
            metric_type="counter",
        ),
        MetricDefinition(
            name="doc_process_duration_seconds",
            description="Document processing duration",
            unit="s",
            metric_type="histogram",
        ),
        MetricDefinition(
            name="doc_process_cache_hits_total",
            description="Cache hits for processed documents",
            unit="1",
            metric_type="counter",
        ),
        MetricDefinition(
            name="doc_process_errors_total",
            description="Document processing errors by type",
            unit="1",
            metric_type="counter",
        ),
    ]

    def __init__(self) -> None:
        """Initialize metrics with service namespace."""
        super().__init__("doc_process_service", self.DEFINITIONS)

    @classmethod
    def initialize(cls) -> DocProcessMetrics:
        """Initialize singleton metrics instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def get(cls) -> DocProcessMetrics:
        """Get metrics instance.

        Raises:
            RuntimeError: If metrics not initialized.

        """
        if cls._instance is None:
            msg = "Metrics not initialized. Call initialize() first."
            raise RuntimeError(msg)
        return cls._instance

    def record_request(self, level: str, *, cached: bool) -> None:
        """Record a processing request.

        Args:
            level: Processing level name.
            cached: Whether result was from cache.

        """
        self._get_counter("doc_process_requests_total").add(1, {"level": level, "cached": str(cached).lower()})

    def record_duration(self, seconds: float, level: str, *, success: bool) -> None:
        """Record processing duration.

        Args:
            seconds: Duration in seconds.
            level: Processing level name.
            success: Whether processing succeeded.

        """
        self._get_histogram("doc_process_duration_seconds").record(
            seconds, {"level": level, "success": str(success).lower()}
        )

    def record_cache_hit(self, level: str) -> None:
        """Record a cache hit.

        Args:
            level: Processing level name.

        """
        self._get_counter("doc_process_cache_hits_total").add(1, {"level": level})

    def record_error(self, error_type: str) -> None:
        """Record a processing error.

        Args:
            error_type: Type of error encountered.

        """
        self._get_counter("doc_process_errors_total").add(1, {"error_type": error_type})

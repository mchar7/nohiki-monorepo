"""Domain metrics for job-storage-service ingest pipeline."""

from __future__ import annotations

from functools import lru_cache

from nohiki_observability.metrics.builders import DomainMetricsBase, MetricDefinition

_DEFINITIONS = [
    MetricDefinition(
        "nohiki_enrichment_completion_orphan_total",
        "EnrichmentCompleted events arriving for a URL with no matching saga row",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_stale_saga_sweep_failures_total",
        "Stale saga sweep iterations that failed with an exception",
        "1",
        "counter",
    ),
]


class IngestMetrics(DomainMetricsBase):
    """Metrics for the saga-driven ingest pipeline."""

    def __init__(self) -> None:
        """Initialize ingest metrics."""
        super().__init__("nohiki.job_storage.ingest", _DEFINITIONS)

    def record_orphan_completion(self) -> None:
        """Record an EnrichmentCompleted that has no matching saga row."""
        self._get_counter("nohiki_enrichment_completion_orphan_total").add(1)

    def record_stale_saga_sweep_failure(self) -> None:
        """Record a failure of the stale saga sweep loop."""
        self._get_counter("nohiki_stale_saga_sweep_failures_total").add(1)


@lru_cache(maxsize=1)
def get_ingest_metrics() -> IngestMetrics:
    """Get the singleton IngestMetrics instance."""
    return IngestMetrics()

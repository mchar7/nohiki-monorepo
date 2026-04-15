"""Job enrichment metrics for job-ingest-enrichment-service."""

from __future__ import annotations

from functools import lru_cache

from nohiki_observability.metrics.builders import DomainMetricsBase, MetricDefinition

DEFINITIONS = [
    MetricDefinition(
        "nohiki_job_enrichment_pipeline_stage_total",
        "Pipeline stage transitions",
        "1",
        "counter",
    ),
    MetricDefinition(
        "nohiki_job_enrichment_saga_duration_seconds",
        "Saga completion latency",
        "s",
        "histogram",
    ),
    MetricDefinition(
        "nohiki_job_enrichment_errors_total",
        "Job enrichment errors",
        "1",
        "counter",
    ),
]


class JobEnrichmentMetrics(DomainMetricsBase):
    """Job enrichment pipeline metrics."""

    def __init__(self) -> None:
        """Initialize job enrichment metrics."""
        super().__init__("nohiki.job_enrichment", DEFINITIONS)

    def record_pipeline_stage(self, stage: str) -> None:
        """Record a pipeline stage transition."""
        self._get_counter("nohiki_job_enrichment_pipeline_stage_total").add(1, {"stage": stage})

    def record_saga_completion(
        self,
        saga_type: str,
        duration_seconds: float,
        *,
        success: bool = True,
    ) -> None:
        """Record saga completion metrics."""
        attrs = {"saga_type": saga_type, "status": "success" if success else "error"}
        self._get_histogram("nohiki_job_enrichment_saga_duration_seconds").record(duration_seconds, attrs)

        if not success:
            self._get_counter("nohiki_job_enrichment_errors_total").add(1, {"operation": saga_type})


@lru_cache(maxsize=1)
def get_job_enrichment_metrics() -> JobEnrichmentMetrics:
    """Get singleton JobEnrichmentMetrics instance."""
    return JobEnrichmentMetrics()

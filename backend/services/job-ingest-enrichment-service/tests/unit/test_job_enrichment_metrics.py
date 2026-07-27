"""Tests for JobEnrichmentMetrics."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from job_ingest_enrichment_service.metrics import (
    JobEnrichmentMetrics,
    get_job_enrichment_metrics,
)
from opentelemetry.metrics import Counter, Histogram


@pytest.fixture
def metrics() -> JobEnrichmentMetrics:
    """Create a fresh JobEnrichmentMetrics instance for testing."""
    return JobEnrichmentMetrics()


class TestJobEnrichmentMetrics:
    """Tests for JobEnrichmentMetrics class."""

    def teardown_method(self) -> None:
        """Clear the cached metrics instance after each test."""
        get_job_enrichment_metrics.cache_clear()

    def test_record_pipeline_stage(self, metrics: JobEnrichmentMetrics) -> None:
        """Test recording pipeline stage transitions."""
        mock_counter = MagicMock(spec=Counter)
        metrics._instruments["nohiki_job_enrichment_pipeline_stage_total"] = mock_counter

        metrics.record_pipeline_stage("accepted")

        mock_counter.add.assert_called_once_with(1, {"stage": "accepted"})

    def test_record_pipeline_stage_different_stages(self, metrics: JobEnrichmentMetrics) -> None:
        """Test recording different pipeline stages."""
        mock_counter = MagicMock(spec=Counter)
        metrics._instruments["nohiki_job_enrichment_pipeline_stage_total"] = mock_counter

        metrics.record_pipeline_stage("enriched")
        metrics.record_pipeline_stage("completed")

        assert mock_counter.add.call_count == 2

    def test_record_saga_completion_success(self, metrics: JobEnrichmentMetrics) -> None:
        """Test recording successful saga completion."""
        mock_histogram = MagicMock(spec=Histogram)
        metrics._instruments["nohiki_job_enrichment_saga_duration_seconds"] = mock_histogram

        metrics.record_saga_completion("enrichment", 1.5, success=True)

        mock_histogram.record.assert_called_once_with(1.5, {"saga_type": "enrichment", "status": "success"})

    def test_record_saga_completion_failure(self, metrics: JobEnrichmentMetrics) -> None:
        """Test recording failed saga completion."""
        mock_histogram = MagicMock(spec=Histogram)
        mock_counter = MagicMock(spec=Counter)
        metrics._instruments["nohiki_job_enrichment_saga_duration_seconds"] = mock_histogram
        metrics._instruments["nohiki_job_enrichment_errors_total"] = mock_counter

        metrics.record_saga_completion("enrichment", 2.0, success=False)

        mock_histogram.record.assert_called_once_with(2.0, {"saga_type": "enrichment", "status": "error"})
        mock_counter.add.assert_called_once_with(1, {"operation": "enrichment"})

    def test_get_job_enrichment_metrics_singleton(self) -> None:
        """Test that get_job_enrichment_metrics returns a singleton."""
        get_job_enrichment_metrics.cache_clear()

        metrics1 = get_job_enrichment_metrics()
        metrics2 = get_job_enrichment_metrics()

        assert metrics1 is metrics2

    def test_metrics_instruments_created(self, metrics: JobEnrichmentMetrics) -> None:
        """Test that expected instruments are created."""
        expected_instruments = {
            "nohiki_job_enrichment_pipeline_stage_total",
            "nohiki_job_enrichment_saga_duration_seconds",
            "nohiki_job_enrichment_errors_total",
        }
        assert set(metrics._instruments.keys()) == expected_instruments

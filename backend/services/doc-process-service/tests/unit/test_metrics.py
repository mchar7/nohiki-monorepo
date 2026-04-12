"""Tests for doc_process_service.metrics module."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from doc_process_service.metrics import DocProcessMetrics


@pytest.fixture(autouse=True)
def _reset_metrics_singleton() -> None:
    """Reset the singleton instance before each test."""
    DocProcessMetrics._instance = None


@pytest.fixture
def mock_init() -> Generator[MagicMock]:
    """Mock __init__ to prevent actual initialization."""
    with patch.object(DocProcessMetrics, "__init__", return_value=None) as mock:
        yield mock


class TestDocProcessMetricsInit:
    """Tests for DocProcessMetrics initialization."""

    def test_definitions_exist(self) -> None:
        """Test that metric definitions are defined."""
        assert len(DocProcessMetrics.DEFINITIONS) == 4

    def test_definitions_have_required_fields(self) -> None:
        """Test that all metric definitions have required fields."""
        for definition in DocProcessMetrics.DEFINITIONS:
            assert definition.name
            assert definition.description
            assert definition.unit
            assert definition.metric_type in ("counter", "histogram", "gauge")


class TestDocProcessMetricsInitialize:
    """Tests for initialize class method."""

    def test_initialize_creates_instance(self, mock_init: MagicMock) -> None:
        """Test initialize creates singleton instance."""
        result = DocProcessMetrics.initialize()

        assert result is DocProcessMetrics._instance
        mock_init.assert_called_once()

    def test_initialize_returns_same_instance(self, mock_init: MagicMock) -> None:
        """Test initialize returns same instance on subsequent calls."""
        first = DocProcessMetrics.initialize()
        second = DocProcessMetrics.initialize()

        assert first is second
        mock_init.assert_called_once()


class TestDocProcessMetricsGet:
    """Tests for get class method."""

    def test_get_raises_when_not_initialized(self) -> None:
        """Test get raises RuntimeError when not initialized."""
        with pytest.raises(RuntimeError, match="Metrics not initialized"):
            DocProcessMetrics.get()

    def test_get_returns_instance_when_initialized(self, mock_init: MagicMock) -> None:
        """Test get returns instance after initialization."""
        assert mock_init is not None
        DocProcessMetrics.initialize()

        result = DocProcessMetrics.get()

        assert result is DocProcessMetrics._instance


class TestDocProcessMetricsRecordRequest:
    """Tests for record_request method."""

    def test_record_request_increments_counter(self, mock_init: MagicMock) -> None:
        """Test record_request increments requests counter."""
        assert mock_init is not None
        mock_counter = MagicMock()

        with patch.object(DocProcessMetrics, "_get_counter", return_value=mock_counter) as mock_get:
            metrics = DocProcessMetrics.initialize()
            metrics.record_request("tables", cached=False)

            mock_get.assert_called_once_with("doc_process_requests_total")
            mock_counter.add.assert_called_once_with(1, {"level": "tables", "cached": "false"})

    def test_record_request_with_cache_hit(self, mock_init: MagicMock) -> None:
        """Test record_request records cache hit correctly."""
        assert mock_init is not None
        mock_counter = MagicMock()

        with patch.object(DocProcessMetrics, "_get_counter", return_value=mock_counter):
            metrics = DocProcessMetrics.initialize()
            metrics.record_request("ocr", cached=True)

            mock_counter.add.assert_called_once_with(1, {"level": "ocr", "cached": "true"})


class TestDocProcessMetricsRecordDuration:
    """Tests for record_duration method."""

    def test_record_duration_records_histogram(self, mock_init: MagicMock) -> None:
        """Test record_duration records to histogram."""
        assert mock_init is not None
        mock_histogram = MagicMock()

        with patch.object(DocProcessMetrics, "_get_histogram", return_value=mock_histogram) as mock_get:
            metrics = DocProcessMetrics.initialize()
            metrics.record_duration(1.5, "tables", success=True)

            mock_get.assert_called_once_with("doc_process_duration_seconds")
            mock_histogram.record.assert_called_once_with(1.5, {"level": "tables", "success": "true"})

    def test_record_duration_on_failure(self, mock_init: MagicMock) -> None:
        """Test record_duration records failure correctly."""
        assert mock_init is not None
        mock_histogram = MagicMock()

        with patch.object(DocProcessMetrics, "_get_histogram", return_value=mock_histogram):
            metrics = DocProcessMetrics.initialize()
            metrics.record_duration(5.0, "full", success=False)

            mock_histogram.record.assert_called_once_with(5.0, {"level": "full", "success": "false"})


class TestDocProcessMetricsRecordCacheHit:
    """Tests for record_cache_hit method."""

    def test_record_cache_hit(self, mock_init: MagicMock) -> None:
        """Test record_cache_hit increments cache hits counter."""
        assert mock_init is not None
        mock_counter = MagicMock()

        with patch.object(DocProcessMetrics, "_get_counter", return_value=mock_counter) as mock_get:
            metrics = DocProcessMetrics.initialize()
            metrics.record_cache_hit("basic")

            mock_get.assert_called_once_with("doc_process_cache_hits_total")
            mock_counter.add.assert_called_once_with(1, {"level": "basic"})


class TestDocProcessMetricsRecordError:
    """Tests for record_error method."""

    def test_record_error(self, mock_init: MagicMock) -> None:
        """Test record_error increments errors counter."""
        assert mock_init is not None
        mock_counter = MagicMock()

        with patch.object(DocProcessMetrics, "_get_counter", return_value=mock_counter) as mock_get:
            metrics = DocProcessMetrics.initialize()
            metrics.record_error("timeout")

            mock_get.assert_called_once_with("doc_process_errors_total")
            mock_counter.add.assert_called_once_with(1, {"error_type": "timeout"})

    def test_record_error_different_types(self, mock_init: MagicMock) -> None:
        """Test record_error with different error types."""
        assert mock_init is not None
        mock_counter = MagicMock()

        with patch.object(DocProcessMetrics, "_get_counter", return_value=mock_counter):
            metrics = DocProcessMetrics.initialize()

            metrics.record_error("connection_error")
            metrics.record_error("validation_error")

            assert mock_counter.add.call_count == 2

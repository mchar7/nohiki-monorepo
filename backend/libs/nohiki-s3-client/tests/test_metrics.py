"""Tests for S3 metrics module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from nohiki_s3_client.metrics import S3Metrics, get_s3_metrics


class TestS3Metrics:
    """Tests for S3Metrics class."""

    @pytest.fixture
    def mock_instruments(self) -> dict[str, MagicMock]:
        """Create mock instruments for testing."""
        return {
            "operations": MagicMock(),
            "latency": MagicMock(),
            "bytes_uploaded": MagicMock(),
            "bytes_downloaded": MagicMock(),
            "errors": MagicMock(),
        }

    @pytest.fixture
    def metrics(self, mock_instruments: dict[str, MagicMock]) -> S3Metrics:
        """Create S3Metrics instance with mocked instruments."""
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = [
            mock_instruments["operations"],
            mock_instruments["bytes_uploaded"],
            mock_instruments["bytes_downloaded"],
            mock_instruments["errors"],
        ]
        mock_meter.create_histogram.return_value = mock_instruments["latency"]

        with patch("opentelemetry.metrics.get_meter", return_value=mock_meter):
            return S3Metrics()

    def test_initialization_creates_metrics(self) -> None:
        """Test that initialization creates all expected metrics."""
        mock_meter = MagicMock()

        with patch("opentelemetry.metrics.get_meter", return_value=mock_meter):
            S3Metrics()

        # Verify all metrics were created
        assert mock_meter.create_counter.call_count == 4
        assert mock_meter.create_histogram.call_count == 1

        # Verify metric names and descriptions by checking call args
        counter_calls = mock_meter.create_counter.call_args_list
        names_args = {call.args[0] for call in counter_calls}
        assert "nohiki_s3_operations_total" in names_args
        assert "nohiki_s3_bytes_uploaded_total" in names_args
        assert "nohiki_s3_bytes_downloaded_total" in names_args
        assert "nohiki_s3_errors_total" in names_args

        # Verify histogram
        hist_call = mock_meter.create_histogram.call_args
        assert hist_call.args[0] == "nohiki_s3_operation_duration_seconds"

    def test_record_operation_success(self, metrics: S3Metrics, mock_instruments: dict[str, MagicMock]) -> None:
        """Test recording a successful operation."""
        metrics.record_operation("upload", 0.5, success=True, bytes_count=1024, bucket="test-bucket")

        # Verify operations counter was incremented
        mock_instruments["operations"].add.assert_called_once()
        args = mock_instruments["operations"].add.call_args[0]
        assert args[0] == 1
        assert args[1]["operation"] == "upload"
        assert args[1]["status"] == "success"
        assert args[1]["bucket"] == "test-bucket"

        # Verify latency was recorded
        mock_instruments["latency"].record.assert_called_once()
        lat_args = mock_instruments["latency"].record.call_args[0]
        assert lat_args[0] == pytest.approx(0.5)

        # Verify bytes uploaded was recorded
        bytes_args = mock_instruments["bytes_uploaded"].add.call_args[0]
        assert bytes_args[0] == 1024
        assert bytes_args[1]["operation"] == "upload"

    def test_record_operation_error(self, metrics: S3Metrics, mock_instruments: dict[str, MagicMock]) -> None:
        """Test recording a failed operation."""
        metrics.record_operation("download", 1.0, success=False, bucket="test-bucket")

        # Verify operations counter with error status
        mock_instruments["operations"].add.assert_called_once()
        args = mock_instruments["operations"].add.call_args[0]
        assert args[1]["status"] == "error"

        # Verify error counter was incremented
        err_args = mock_instruments["errors"].add.call_args[0]
        assert err_args[0] == 1
        assert err_args[1]["status"] == "error"

    def test_record_operation_without_bucket(self, metrics: S3Metrics, mock_instruments: dict[str, MagicMock]) -> None:
        """Test recording operation without bucket."""
        metrics.record_operation("list_objects", 0.1, success=True)

        # Verify bucket is not in attributes
        args = mock_instruments["operations"].add.call_args[0]
        assert "bucket" not in args[1]

    def test_record_upload_operations(self, mock_instruments: dict[str, MagicMock]) -> None:
        """Test bytes tracking for various upload operations."""
        upload_ops = ["upload", "put_object", "upload_fileobj"]

        for op in upload_ops:
            for mock in mock_instruments.values():
                mock.reset_mock()

            mock_meter = MagicMock()
            mock_meter.create_counter.side_effect = [
                mock_instruments["operations"],
                mock_instruments["bytes_uploaded"],
                mock_instruments["bytes_downloaded"],
                mock_instruments["errors"],
            ]
            mock_meter.create_histogram.return_value = mock_instruments["latency"]

            with patch("opentelemetry.metrics.get_meter", return_value=mock_meter):
                metrics = S3Metrics()

            metrics.record_operation(op, 0.1, success=True, bytes_count=100)

            assert mock_instruments["bytes_uploaded"].add.call_count == 1
            assert mock_instruments["bytes_downloaded"].add.call_count == 0

    def test_record_download_operations(self, mock_instruments: dict[str, MagicMock]) -> None:
        """Test bytes tracking for various download operations."""
        download_ops = ["download", "get_object", "download_fileobj"]

        for op in download_ops:
            for mock in mock_instruments.values():
                mock.reset_mock()

            mock_meter = MagicMock()
            mock_meter.create_counter.side_effect = [
                mock_instruments["operations"],
                mock_instruments["bytes_uploaded"],
                mock_instruments["bytes_downloaded"],
                mock_instruments["errors"],
            ]
            mock_meter.create_histogram.return_value = mock_instruments["latency"]

            with patch("opentelemetry.metrics.get_meter", return_value=mock_meter):
                metrics = S3Metrics()

            metrics.record_operation(op, 0.1, success=True, bytes_count=100)

            assert mock_instruments["bytes_downloaded"].add.call_count == 1
            assert mock_instruments["bytes_uploaded"].add.call_count == 0

    def test_record_operation_zero_bytes(self, metrics: S3Metrics, mock_instruments: dict[str, MagicMock]) -> None:
        """Test that zero bytes doesn't trigger byte counters."""
        metrics.record_operation("upload", 0.1, success=True, bytes_count=0)

        assert mock_instruments["bytes_uploaded"].add.call_count == 0
        assert mock_instruments["bytes_downloaded"].add.call_count == 0

    def test_record_operation_other_operations(
        self, metrics: S3Metrics, mock_instruments: dict[str, MagicMock]
    ) -> None:
        """Test operations that don't trigger byte counters."""
        metrics.record_operation("list_objects", 0.1, success=True, bytes_count=100)

        assert mock_instruments["bytes_uploaded"].add.call_count == 0
        assert mock_instruments["bytes_downloaded"].add.call_count == 0


class TestGetS3Metrics:
    """Tests for get_s3_metrics singleton function."""

    def setup_method(self) -> None:
        """Clear cache before each test."""
        get_s3_metrics.cache_clear()

    def test_returns_singleton_instance(self) -> None:
        """Test that get_s3_metrics returns same instance."""
        with patch("opentelemetry.metrics.get_meter"):
            metrics1 = get_s3_metrics()
            metrics2 = get_s3_metrics()

        assert metrics1 is metrics2

    def test_returns_s3_metrics_instance(self) -> None:
        """Test that get_s3_metrics returns S3Metrics instance."""
        with patch("opentelemetry.metrics.get_meter"):
            metrics = get_s3_metrics()

        assert isinstance(metrics, S3Metrics)

    def test_caches_instance(self) -> None:
        """Test that instance is cached via lru_cache."""
        with patch("opentelemetry.metrics.get_meter") as mock_get_meter:
            get_s3_metrics()
            get_s3_metrics()
            get_s3_metrics()

        assert mock_get_meter.call_count == 1

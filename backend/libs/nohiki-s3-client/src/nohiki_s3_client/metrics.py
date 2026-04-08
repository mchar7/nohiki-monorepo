"""S3 metrics - owned by nohiki-s3-client."""

from __future__ import annotations

from functools import lru_cache

from opentelemetry import metrics


class S3Metrics:
    """S3 storage metrics using OpenTelemetry."""

    def __init__(self) -> None:
        """Initialize S3 metrics with OpenTelemetry meter."""
        self._meter = metrics.get_meter("nohiki.s3")

        self.operations = self._meter.create_counter(
            "nohiki_s3_operations_total",
            description="Total S3 operations",
            unit="1",
        )
        self.latency = self._meter.create_histogram(
            "nohiki_s3_operation_duration_seconds",
            description="S3 operation latency",
            unit="s",
        )
        self.bytes_uploaded = self._meter.create_counter(
            "nohiki_s3_bytes_uploaded_total",
            description="Total bytes uploaded to S3",
            unit="By",
        )
        self.bytes_downloaded = self._meter.create_counter(
            "nohiki_s3_bytes_downloaded_total",
            description="Total bytes downloaded from S3",
            unit="By",
        )
        self.errors = self._meter.create_counter(
            "nohiki_s3_errors_total",
            description="S3 operation errors",
            unit="1",
        )

    def record_operation(
        self,
        operation: str,
        duration_seconds: float,
        *,
        success: bool = True,
        bytes_count: int = 0,
        bucket: str | None = None,
    ) -> None:
        """Record an S3 operation."""
        attrs: dict[str, str] = {
            "operation": operation,
            "status": "success" if success else "error",
        }
        if bucket:
            attrs["bucket"] = bucket

        self.operations.add(1, attrs)
        self.latency.record(duration_seconds, attrs)

        if bytes_count > 0:
            if operation in ("upload", "put_object", "upload_fileobj"):
                self.bytes_uploaded.add(bytes_count, attrs)
            elif operation in ("download", "get_object", "download_fileobj"):
                self.bytes_downloaded.add(bytes_count, attrs)

        if not success:
            self.errors.add(1, attrs)


@lru_cache(maxsize=1)
def get_s3_metrics() -> S3Metrics:
    """Get singleton S3Metrics instance."""
    return S3Metrics()

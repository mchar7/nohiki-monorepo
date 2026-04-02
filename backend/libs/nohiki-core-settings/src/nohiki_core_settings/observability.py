"""Observability settings for Nohiki services."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoggingSettings(BaseModel):
    """Structured logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Log level threshold",
    )
    format: Literal["json", "console"] = Field(
        default="json",
        description="Log output format (json for production, console for dev)",
    )
    include_trace_id: bool = Field(
        default=True,
        description="Include OpenTelemetry trace ID in log records",
    )


class TracingSettings(BaseModel):
    """Distributed tracing configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable distributed tracing",
    )
    sample_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling rate (0.0 = none, 1.0 = all)",
    )


class PrometheusSettings(BaseModel):
    """Prometheus metrics export configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics endpoint",
    )
    endpoint_path: str = Field(
        default="/metrics",
        description="HTTP path for Prometheus scraping",
    )


class ObservabilitySettings(BaseModel):
    """OpenTelemetry, logging, and metrics configuration.

    Provides observability configuration for Nohiki services,
    including OTEL collector, Prometheus metrics, and logging.

    Environment variables (with service prefix):
        {PREFIX}__OBSERVABILITY__OTEL_ENDPOINT=http://collector:4317
        {PREFIX}__OBSERVABILITY__LOGGING__LEVEL=DEBUG
        {PREFIX}__OBSERVABILITY__TRACING__SAMPLE_RATE=0.5
        {PREFIX}__OBSERVABILITY__PROMETHEUS__ENABLED=true
    """

    otel_endpoint: str = Field(
        default="",
        description="OTEL Collector gRPC endpoint (empty to disable)",
    )
    otel_insecure: bool = Field(
        default=True,
        description="Use insecure (non-TLS) connection to OTEL Collector",
    )
    otel_service_name: str | None = Field(
        default=None,
        description="Override service name for OTEL (defaults to service_name)",
    )

    logging: LoggingSettings = Field(
        default_factory=LoggingSettings,
        description="Logging configuration",
    )
    tracing: TracingSettings = Field(
        default_factory=TracingSettings,
        description="Tracing configuration",
    )
    prometheus: PrometheusSettings = Field(
        default_factory=PrometheusSettings,
        description="Prometheus metrics configuration",
    )

"""Fluent builder for observability configuration.

Provides a builder pattern for convenient observability setup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from .config import ObservabilityOptions, OtelConfig

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .observability import Observability


class ObservabilityBuilder:
    """Builder pattern for Observability configuration.

    Provides a fluent API for constructing ObservabilityOptions
    with sensible defaults and validation.

    Example:
        options = (
            ObservabilityBuilder()
            .service("my-service", "1.0.0")
            .otel_endpoint("http://collector:4317")
            .environment("production")
            .build()
        )
    """

    __slots__ = (
        "_environment",
        "_instrument_grpc",
        "_instrument_httpx",
        "_instrument_redis",
        "_log_level",
        "_otel_enabled",
        "_otel_endpoint",
        "_otel_headers",
        "_otel_insecure",
        "_resource_attributes",
        "_sample_rate",
        "_service_name",
        "_service_version",
        "_tracing_enabled",
    )

    def __init__(self) -> None:
        """Initialize builder with default values."""
        self._service_name: str = ""
        self._service_version: str = "0.0.0"
        self._environment: str = "development"
        self._log_level: str = "INFO"
        self._sample_rate: float = 1.0
        self._tracing_enabled: bool = True
        self._otel_enabled: bool = True
        self._otel_endpoint: str | None = None
        self._otel_insecure: bool = True
        self._otel_headers: dict[str, str] = {}
        self._resource_attributes: dict[str, str] = {}
        self._instrument_httpx: bool = True
        self._instrument_redis: bool = False
        self._instrument_grpc: bool = False

    def service(self, name: str, version: str = "0.0.0") -> Self:
        """Set service name and version."""
        self._service_name = name
        self._service_version = version
        return self

    def environment(self, env: str) -> Self:
        """Set deployment environment (e.g., 'production', 'development')."""
        self._environment = env
        return self

    def log_level(self, level: str) -> Self:
        """Set minimum log level (DEBUG, INFO, WARNING, ERROR)."""
        self._log_level = level.upper()
        return self

    def sample_rate(self, rate: float) -> Self:
        """Set trace sampling rate (0.0 to 1.0)."""
        if not 0.0 <= rate <= 1.0:
            msg = "sample_rate must be between 0.0 and 1.0"
            raise ValueError(msg)
        self._sample_rate = rate
        return self

    def tracing_enabled(self, *, enabled: bool) -> Self:
        """Enable or disable distributed tracing."""
        self._tracing_enabled = enabled
        return self

    def otel_endpoint(self, endpoint: str | None, *, insecure: bool = True) -> Self:
        """Set OpenTelemetry collector endpoint."""
        self._otel_endpoint = endpoint or None
        self._otel_insecure = insecure
        return self

    def otel_headers(self, headers: Mapping[str, str]) -> Self:
        """Set headers for OpenTelemetry exporter."""
        self._otel_headers = dict(headers)
        return self

    def resource_attributes(self, attributes: Mapping[str, str]) -> Self:
        """Set additional OpenTelemetry resource attributes."""
        self._resource_attributes = dict(attributes)
        return self

    def instrument_httpx(self, *, enabled: bool = True) -> Self:
        """Enable/disable HTTPX auto-instrumentation."""
        self._instrument_httpx = enabled
        return self

    def instrument_redis(self, *, enabled: bool = True) -> Self:
        """Enable/disable Redis auto-instrumentation."""
        self._instrument_redis = enabled
        return self

    def instrument_grpc(self, *, enabled: bool = True) -> Self:
        """Enable/disable gRPC auto-instrumentation."""
        self._instrument_grpc = enabled
        return self

    def build(self) -> Observability:
        """Build the final Observability instance."""
        from .observability import Observability  # noqa: PLC0415

        if not self._service_name:
            msg = "service_name is required"
            raise ValueError(msg)

        options = ObservabilityOptions(
            service_name=self._service_name,
            service_version=self._service_version,
            environment=self._environment,
            otel=OtelConfig(
                endpoint=self._otel_endpoint,
                insecure=self._otel_insecure,
                headers=self._otel_headers,
            ),
            log_level=self._log_level,
            sample_rate=self._sample_rate,
            tracing_enabled=self._tracing_enabled,
            instrument_redis=self._instrument_redis,
            instrument_grpc=self._instrument_grpc,
            instrument_httpx=self._instrument_httpx,
            resource_attributes=self._resource_attributes,
        )
        return Observability(options)

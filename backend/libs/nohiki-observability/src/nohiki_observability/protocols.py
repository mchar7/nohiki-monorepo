"""Protocol definitions for observability configuration typing.

These protocols allow services to implement observability config
in their settings classes without hard coupling to specific implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LoggingConfig(Protocol):
    """Protocol for nested logging configuration."""

    @property
    def level(self) -> str:
        """Log level threshold."""
        ...


@runtime_checkable
class TracingConfig(Protocol):
    """Protocol for nested tracing configuration."""

    @property
    def enabled(self) -> bool:
        """Whether tracing is enabled."""
        ...

    @property
    def sample_rate(self) -> float:
        """Trace sampling rate (0.0 = none, 1.0 = all)."""
        ...


@runtime_checkable
class PrometheusConfig(Protocol):
    """Protocol for Prometheus metrics configuration."""

    @property
    def enabled(self) -> bool:
        """Whether Prometheus metrics endpoint is enabled."""
        ...


@runtime_checkable
class ObservabilityConfig(Protocol):
    """Protocol for observability section of service settings.

    This protocol defines what the observability configuration must expose,
    allowing services to implement it in their own Pydantic settings classes.
    """

    @property
    def otel_service_name(self) -> str | None:
        """Override service name for telemetry (defaults to service_name)."""
        ...

    @property
    def otel_endpoint(self) -> str:
        """OTEL collector endpoint URL (e.g., http://localhost:4317)."""
        ...

    @property
    def otel_insecure(self) -> bool:
        """Whether to use insecure gRPC connection to OTEL collector."""
        ...

    @property
    def logging(self) -> LoggingConfig:
        """Logging configuration."""
        ...

    @property
    def tracing(self) -> TracingConfig:
        """Tracing configuration."""
        ...

    @property
    def prometheus(self) -> PrometheusConfig:
        """Prometheus metrics configuration."""
        ...


@runtime_checkable
class ObservabilitySettingsProvider(Protocol):
    """Protocol for service settings that provide observability configuration.

    Services implement this protocol in their main settings class
    to enable automatic observability initialization.

    Example:
        class MyServiceSettings:
            service_name: str = "my-service"
            service_version: str = "1.0.0"
            debug: bool = False
            instrument_redis: bool = False
            observability: ObservabilitySettings

    """

    @property
    def service_name(self) -> str:
        """Service name for identification."""
        ...

    @property
    def service_version(self) -> str:
        """Service version string."""
        ...

    @property
    def debug(self) -> bool:
        """Whether debug mode is enabled."""
        ...

    @property
    def instrument_redis(self) -> bool:
        """Whether to auto-instrument Redis clients."""
        ...

    @property
    def observability(self) -> ObservabilityConfig:
        """Observability configuration section."""
        ...

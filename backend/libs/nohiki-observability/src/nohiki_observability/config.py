"""Configuration dataclasses for observability options.

These dataclasses hold the resolved configuration used by the Observability class.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OtelConfig:
    """OpenTelemetry export configuration."""

    endpoint: str | None
    insecure: bool = True
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        """Check if OTEL export is enabled (endpoint is configured)."""
        return bool(self.endpoint)


@dataclass(frozen=True, slots=True)
class ObservabilityOptions:
    """Immutable configuration for observability initialization."""

    service_name: str
    service_version: str
    environment: str
    otel: OtelConfig
    log_level: str = "INFO"
    sample_rate: float = 1.0
    tracing_enabled: bool = True
    instrument_redis: bool = False
    instrument_grpc: bool = True
    instrument_httpx: bool = True
    resource_attributes: Mapping[str, str] = field(default_factory=dict)

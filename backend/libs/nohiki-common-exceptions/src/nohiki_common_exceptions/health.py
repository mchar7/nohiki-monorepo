"""Health probe protocol and types for domain-owned health checking.

Each library that provides access to an external dependency implements
this protocol. Services declare which probes they need, and the health
router aggregates results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Self, runtime_checkable


class HealthStatus(Enum):
    """Health check status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    """Standardized health probe result.

    All health probes return this type for consistent aggregation.
    """

    name: str
    status: HealthStatus
    message: str
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)

    def is_healthy(self) -> bool:
        """Return True if status is HEALTHY or DEGRADED."""
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "healthy": self.is_healthy(),
            "details": self.details,
        }


@runtime_checkable
class HealthProbe(Protocol):
    """Protocol for dependency health probes.

    Each library that wraps an external dependency (Redis, Kafka, S3, etc.)
    implements this protocol to provide health checking capability.
    """

    @property
    def name(self) -> str:
        """Probe identifier (e.g., 'redis', 'kafka', 'database')."""
        ...

    async def check(self) -> HealthProbeResult:
        """Execute health check and return result."""
        ...


class HealthProbeTimer:
    """Context manager for timing health probe operations."""

    __slots__ = ("_end", "_start")

    def __init__(self) -> None:
        """Initialize timer with zero values."""
        self._start: float = 0.0
        self._end: float = 0.0

    def __enter__(self) -> Self:
        """Start the timer."""
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        """Stop the timer."""
        self._end = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        """Return elapsed time in milliseconds."""
        return (self._end - self._start) * 1000


def create_healthy_result(
    name: str,
    message: str,
    latency_ms: float,
    details: dict[str, Any] | None = None,
) -> HealthProbeResult:
    """Create a HEALTHY probe result."""
    return HealthProbeResult(
        name=name,
        status=HealthStatus.HEALTHY,
        message=message,
        latency_ms=latency_ms,
        details=details or {},
    )


def create_degraded_result(
    name: str,
    message: str,
    latency_ms: float,
    details: dict[str, Any] | None = None,
) -> HealthProbeResult:
    """Create a DEGRADED probe result."""
    return HealthProbeResult(
        name=name,
        status=HealthStatus.DEGRADED,
        message=message,
        latency_ms=latency_ms,
        details=details or {},
    )


def create_unhealthy_result(
    name: str,
    message: str,
    latency_ms: float,
    details: dict[str, Any] | None = None,
) -> HealthProbeResult:
    """Create an UNHEALTHY probe result."""
    return HealthProbeResult(
        name=name,
        status=HealthStatus.UNHEALTHY,
        message=message,
        latency_ms=latency_ms,
        details=details or {},
    )

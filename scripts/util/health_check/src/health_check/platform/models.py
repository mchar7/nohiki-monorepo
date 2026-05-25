"""Platform-agnostic models for deployment target identification and service state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PlatformTarget(StrEnum):
    """Deployment target for health checks."""

    COMPOSE = "compose"
    KUBERNETES = "kubernetes"


class ServiceStatus(StrEnum):
    """Unified service health status across platforms."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    STOPPED = "stopped"
    CRASHED = "crashed"


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    """Unified service information across deployment platforms."""

    name: str
    status: ServiceStatus
    ready: bool
    restarts: int = 0
    uptime_seconds: float = 0.0
    details: str = ""

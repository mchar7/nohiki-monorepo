"""Re-export shim for deployment_platform.

The canonical implementations live in ``health_check.platform``.
This shim preserves backward-compatible import paths for test consumers.
"""

from __future__ import annotations

from health_check.config.services import INFRASTRUCTURE_SERVICES as INFRA_SERVICES
from health_check.platform import (
    COMPOSE_NAME_MAP,
    K8S_NAME_MAP,
    ComposePlatform,
    ContainerRuntime,
    KubernetesPlatform,
    Platform,
    PlatformTarget,
    ServiceInfo,
    ServiceStatus,
    detect_container_runtime,
    get_platform,
)

__all__ = [
    "COMPOSE_NAME_MAP",
    "INFRA_SERVICES",
    "K8S_NAME_MAP",
    "ComposePlatform",
    "ContainerRuntime",
    "KubernetesPlatform",
    "Platform",
    "PlatformTarget",
    "ServiceInfo",
    "ServiceStatus",
    "detect_container_runtime",
    "get_platform",
]

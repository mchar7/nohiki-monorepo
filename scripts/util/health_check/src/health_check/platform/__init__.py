"""Platform abstraction for health check operations."""

from __future__ import annotations

from health_check.platform.compose import COMPOSE_NAME_MAP, ComposePlatform
from health_check.platform.factory import get_platform
from health_check.platform.kubernetes import K8S_NAME_MAP, KubernetesPlatform
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus
from health_check.platform.protocol import Platform
from health_check.platform.runtime import ContainerRuntime, detect_container_runtime

__all__ = [
    "COMPOSE_NAME_MAP",
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

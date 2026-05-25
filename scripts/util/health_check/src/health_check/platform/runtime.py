"""Container runtime detection for Docker Compose deployments."""

from __future__ import annotations

import os
import shutil
from enum import StrEnum

from health_check.core.exceptions import RuntimeDetectionError


class ContainerRuntime(StrEnum):
    """Supported container runtimes for Compose-based deployments."""

    DOCKER = "docker"
    PODMAN = "podman"


def detect_container_runtime() -> ContainerRuntime:
    """Auto-detect the available container runtime.

    Detection order:
    1. ``CONTAINER_RUNTIME`` environment variable override. If set, the named
       binary MUST exist in ``PATH`` -- fail-fast if it does not.
    2. ``podman`` -- project default; checked first.
    3. ``docker`` -- fallback; checked only if podman is absent.
    4. Neither found → ``RuntimeDetectionError`` with actionable message.

    Returns:
        The detected ``ContainerRuntime``.

    Raises:
        RuntimeDetectionError: If the requested or any supported runtime binary
            is not found in ``PATH``.
    """
    if override := os.environ.get("CONTAINER_RUNTIME"):
        normalised = override.strip().lower()
        if shutil.which(normalised) is None:
            msg = (
                f"CONTAINER_RUNTIME={override!r} but '{normalised}' binary not found in PATH. "
                f"Install {normalised} or unset CONTAINER_RUNTIME."
            )
            raise RuntimeDetectionError(msg)
        try:
            return ContainerRuntime(normalised)
        except ValueError:
            msg = (
                f"CONTAINER_RUNTIME={override!r} is not a supported runtime. "
                f"Supported values: {', '.join(r.value for r in ContainerRuntime)}."
            )
            raise RuntimeDetectionError(msg) from None

    if shutil.which("podman") is not None:
        return ContainerRuntime.PODMAN

    if shutil.which("docker") is not None:
        return ContainerRuntime.DOCKER

    msg = (
        "No container runtime found in PATH. "
        "Install podman (preferred) or docker and ensure it is in PATH, "
        "or set CONTAINER_RUNTIME=<runtime> to specify explicitly."
    )
    raise RuntimeDetectionError(msg)

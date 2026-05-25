"""Factory for creating platform instances from environment or explicit target."""

from __future__ import annotations

import os

from health_check.platform.compose import ComposePlatform
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget
from health_check.platform.protocol import Platform
from health_check.platform.runtime import detect_container_runtime

_PLATFORM_ALIASES: dict[str, PlatformTarget] = {
    "k8s": PlatformTarget.KUBERNETES,
    "kubernetes": PlatformTarget.KUBERNETES,
    "compose": PlatformTarget.COMPOSE,
    "docker-compose": PlatformTarget.COMPOSE,
}


def _resolve_target(target: PlatformTarget | None) -> PlatformTarget:
    """Resolve the deployment target from argument or ``NOHIKI_TARGET`` env var.

    Args:
        target: Explicit target, or ``None`` to read from the environment.

    Returns:
        Resolved ``PlatformTarget``, defaulting to ``COMPOSE``.
    """
    if target is not None:
        return target
    raw = os.getenv("NOHIKI_TARGET", "compose").strip().lower()
    try:
        return _PLATFORM_ALIASES[raw]
    except KeyError as exc:
        choices = ", ".join(sorted(_PLATFORM_ALIASES))
        message = f"Unknown NOHIKI_TARGET {raw!r}; expected one of: {choices}"
        raise ValueError(message) from exc


def get_platform(target: PlatformTarget | None = None) -> Platform:
    """Create a platform instance for the given deployment target.

    Args:
        target: Which platform to create. If ``None``, reads ``NOHIKI_TARGET``
            env var (default: ``"compose"``).

    Returns:
        A ``Platform``-compatible instance.
    """
    resolved = _resolve_target(target)
    match resolved:
        case PlatformTarget.COMPOSE:
            return ComposePlatform(detect_container_runtime())
        case PlatformTarget.KUBERNETES:
            return KubernetesPlatform()

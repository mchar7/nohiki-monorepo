"""Environment construction for Python subprocesses launched by CI checks."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

_SENSITIVE_ENV_SEGMENTS = re.compile(
    r"(?:^|_)(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|DSN|KUBECONFIG|DOCKER_CONFIG)(?:_|$)"
)


def _is_sensitive_env_name(name: str) -> bool:
    """Return whether an inherited environment name carries credential material."""
    normalized_name = name.upper()
    if _SENSITIVE_ENV_SEGMENTS.search(normalized_name):
        return True
    return {"PRIVATE", "KEY"}.issubset(normalized_name.split("_"))


def sanitized_python_env(
    *,
    extra: Mapping[str, str] | None = None,
    python_paths: Iterable[str | Path] = (),
) -> dict[str, str]:
    """Return an inherited environment safe for a uv-managed Python child.

    Host ``PYTHONPATH`` and ``PYTHONHOME`` values can inject ABI-incompatible
    site-packages into the interpreter selected by ``uv run``. Callers that
    genuinely need import paths must pass them explicitly via ``python_paths``.

    Args:
        extra: Additional non-Python environment variables for the child.
        python_paths: Deliberate import paths to expose to the child.

    Returns:
        A copy of the current environment without inherited Python overrides.
    """
    env = {name: value for name, value in os.environ.items() if not _is_sensitive_env_name(name)}
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    if extra:
        env.update(extra)

    paths = tuple(str(path) for path in python_paths)
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    return env

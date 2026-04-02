"""Environment detection utilities."""

from __future__ import annotations

import os

DEVELOPMENT_ENVIRONMENTS: frozenset[str] = frozenset({"development", "dev", "local"})
"""Canonical set of environment names considered non-production."""


def is_development() -> bool:
    """Check if running in development environment (evaluated at runtime).

    Reads the bare ``ENVIRONMENT`` env var (no service prefix). Used during
    settings construction where no settings instance exists yet.
    """
    env = os.environ.get("ENVIRONMENT", "development")
    return env.lower() in DEVELOPMENT_ENVIRONMENTS

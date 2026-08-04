"""Lazy, portable path resolution for the health check module."""

from __future__ import annotations

import os
from pathlib import Path

from nohiki_test_utils.paths import get_repo_root as _discover_repo_root


def get_project_root() -> Path:
    """Return the explicitly configured project root or discover the monorepo."""
    if root := os.environ.get("PROJECT_ROOT"):
        return Path(root)
    return _discover_repo_root()


def get_compose_dir() -> Path:
    """Return the directory containing the Compose deployment."""
    return get_project_root() / "infra" / "compose"


def get_connector_config_dir() -> Path:
    """Return the Kafka Connect connector configuration directory."""
    return get_project_root() / "infra" / "kafka-connect" / "connectors"


def get_manifest_path() -> Path:
    """Return the semantic representation manifest path."""
    return get_project_root() / "data" / "config" / "semantic_representation_manifest.json"

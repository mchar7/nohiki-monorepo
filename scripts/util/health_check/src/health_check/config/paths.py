"""Portable path resolution for the health check module.

All paths are resolved relative to the monorepo root, located via
``nohiki_test_utils.paths.get_repo_root()``. This function checks the
``PROJECT_ROOT`` environment variable first, then walks up the directory tree
looking for a root ``pyproject.toml`` with ``[tool.uv.workspace]``, making
path resolution work on any developer's machine without hardcoding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from nohiki_test_utils.paths import get_repo_root

REPO_ROOT: Final[Path] = get_repo_root()

COMPOSE_DIR: Final[Path] = REPO_ROOT / "infra" / "compose"

CONNECTOR_CONFIG_DIR: Final[Path] = REPO_ROOT / "infra" / "kafka-connect" / "connectors"

MANIFEST_PATH: Final[Path] = REPO_ROOT / "data" / "config" / "semantic_representation_manifest.json"

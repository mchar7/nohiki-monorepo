"""Testing utilities for nohiki-ml-manifest.

Provides helpers for resolving the manifest path in test environments,
where the working directory may not be the repository root.
"""

from __future__ import annotations

from pathlib import Path

from nohiki_test_utils import get_repo_root

from nohiki_ml_manifest.cache import DEFAULT_MANIFEST_PATH


def get_test_manifest_path() -> Path:
    """Resolve the absolute path to the semantic representation manifest for tests.

    Combines the centralized repo root resolution with the manifest's canonical
    relative path, ensuring tests work regardless of working directory.

    Returns:
        Absolute path to the manifest JSON file.
    """
    return get_repo_root() / DEFAULT_MANIFEST_PATH

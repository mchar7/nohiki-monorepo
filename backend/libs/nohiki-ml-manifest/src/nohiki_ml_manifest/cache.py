"""Process-wide singleton cache for the semantic representation manifest."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import ClassVar, Final

from nohiki_ml_manifest.manifest import SemanticRepresentationManifest

DEFAULT_MANIFEST_PATH: Final[Path] = Path("data/config/semantic_representation_manifest.json")
"""Standard path for the manifest JSON, relative to repository root."""


class ManifestCache:
    """Thread-safe, process-wide singleton cache.

    The path argument is accepted on every call but only used on the first
    invocation; subsequent calls return the cached instance.

    Usage in service config::

        def get_manifest() -> SemanticRepresentationManifest:
            return ManifestCache.get(get_settings().manifest_path)

    Call ``ManifestCache.reset()`` in test teardown for isolation.
    """

    _instance: ClassVar[SemanticRepresentationManifest | None] = None
    _lock: ClassVar[Lock] = Lock()

    @classmethod
    def get(cls, path: Path | str) -> SemanticRepresentationManifest:
        """Return the cached manifest, loading from *path* on first call.

        Args:
            path: Path to the manifest JSON file (used only on first call).

        Raises:
            FileNotFoundError: If the manifest file does not exist.
            ValueError: If the manifest JSON is invalid.

        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = SemanticRepresentationManifest.load_from_path(path)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the cached instance (call in test teardown)."""
        with cls._lock:
            cls._instance = None

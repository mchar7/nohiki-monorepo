"""Vector dimension configuration derived from the semantic representation manifest."""

from __future__ import annotations

from typing import Final

from nohiki_ml_manifest import ManifestCache

from health_check.config.paths import MANIFEST_PATH

_TRACKED_ENTITIES: Final[tuple[str, ...]] = ("jobs", "profiles", "skills")
"""Canonical entity names tracked in Qdrant collections."""


def load_skill_collection_name() -> str:
    """Return the Qdrant collection name for skill embeddings from the manifest.

    Derives the name dynamically so manifest-level collection renames propagate
    automatically without editing the health check.

    Returns:
        Qdrant collection name for the skills entity (e.g. ``"skills_v1"``).
    """
    return ManifestCache.get(MANIFEST_PATH).get_collection_name("skills")


def load_expected_dimensions() -> dict[str, dict[str, int]]:
    """Load expected Qdrant vector dimensions from the semantic representation manifest.

    Derives dimensions dynamically from the manifest so that manifest changes
    automatically propagate to the health check without manual constant updates.

    Returns:
        Mapping of ``{collection_name: {vector_name: dimension}}``.
        Example: ``{"jobs_v1": {"muvera": 8192, "colbert": 48}}``.
    """
    manifest = ManifestCache.get(MANIFEST_PATH)
    return {
        manifest.get_collection_name(entity): {
            name: defn.size for name, defn in manifest.get_collection_config(entity).qdrant.vectors.items()
        }
        for entity in _TRACKED_ENTITIES
    }

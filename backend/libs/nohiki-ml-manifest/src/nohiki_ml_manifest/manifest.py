"""SemanticRepresentationManifest: the canonical ML configuration source of truth."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import ClassVar, Self

from nohiki.ml.v1 import EntityType
from pydantic import BaseModel, Field, computed_field

from nohiki_ml_manifest.collections import CollectionConfig, CollectionsConfig
from nohiki_ml_manifest.encoding import (
    DenseConfig,
    LateInteractionConfig,
    MuveraConfig,
    SparseConfig,
)

_ENTITY_ALIASES: dict[str, str] = {
    "job": "jobs",
    "jobs": "jobs",
    "profile": "profiles",
    "profiles": "profiles",
    "skill": "skills",
    "skills": "skills",
    "occupation": "occupations",
    "occupations": "occupations",
}


class SemanticRepresentationManifest(BaseModel):
    """Model-agnostic configuration for all semantic representations.

    All ML parameters are defined here, NOT hardcoded in service code.
    This enables non-destructive model upgrades and parallel experimentation.

    Collection versioning is per-entity: changing the skills embedding model
    only requires incrementing ``collections.skills.version``.
    """

    collections: CollectionsConfig
    late_interaction: LateInteractionConfig = Field(default_factory=LateInteractionConfig)
    muvera: MuveraConfig = Field(default_factory=MuveraConfig)
    sparse: SparseConfig = Field(default_factory=SparseConfig)
    dense: DenseConfig = Field(default_factory=DenseConfig)
    metadata: dict[str, str] = Field(default_factory=dict)

    _ENTITY_ALIASES: ClassVar[dict[str, str]] = _ENTITY_ALIASES

    def _resolve_entity_key(self, entity_type: str | EntityType) -> str:
        """Normalize an entity type to its canonical plural collection key.

        Args:
            entity_type: ``EntityType`` enum or string like ``"job"``/``"jobs"``.

        Returns:
            Canonical key (``"jobs"``, ``"profiles"``, ``"skills"``, or ``"occupations"``).

        Raises:
            ValueError: If the entity type is unrecognised.

        """
        raw = entity_type.name.lower() if isinstance(entity_type, EntityType) else str(entity_type).lower()
        if (key := self._ENTITY_ALIASES.get(raw)) is None:
            msg = f"Unknown entity type: {entity_type!r}. Expected: job, profile, skill, or occupation"
            raise ValueError(msg)
        return key

    def get_collection_config(self, entity_type: str | EntityType) -> CollectionConfig:
        """Return the ``CollectionConfig`` for an entity type.

        Args:
            entity_type: ``EntityType`` enum or string.

        Raises:
            ValueError: If the entity type is unrecognised.

        """
        key = self._resolve_entity_key(entity_type)
        config: CollectionConfig = getattr(self.collections, key)
        return config

    def get_collection_name(self, entity_type: str | EntityType) -> str:
        """Return the Qdrant collection name (e.g. ``jobs_v1``).

        Args:
            entity_type: ``EntityType`` enum or string.

        Raises:
            ValueError: If the entity type is unrecognised.

        """
        key = self._resolve_entity_key(entity_type)
        config: CollectionConfig = getattr(self.collections, key)
        return f"{key}_{config.version}"

    def get_entity_version(self, entity_type: str | EntityType) -> str:
        """Return the version string (e.g. ``"v1"``) for an entity type."""
        return self.get_collection_config(entity_type).version

    @computed_field
    @cached_property
    def muvera_output_dimension(self) -> int:
        """Compute MUVERA FDE output dimension: ``2^k_sim * dim_proj * r_reps``."""
        return (2**self.muvera.k_sim) * self.muvera.dim_proj * self.muvera.r_reps

    @classmethod
    def load_from_path(cls, path: Path | str) -> Self:
        """Load and validate a manifest from a JSON file.

        Args:
            path: Full path to the manifest JSON file.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the JSON is malformed or fails validation.

        """
        path = Path(path)
        if not path.exists():
            msg = f"Manifest file not found: {path}"
            raise FileNotFoundError(msg)
        try:
            return cls.model_validate_json(path.read_text())
        except Exception as exc:
            msg = f"Failed to load manifest from {path}: {exc}"
            raise ValueError(msg) from exc

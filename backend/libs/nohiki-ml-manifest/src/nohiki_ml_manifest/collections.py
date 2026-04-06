"""Qdrant collection schema and entity versioning definitions."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Self

from pydantic import BaseModel, Field, model_validator


class QdrantVectorDefinition(BaseModel):
    """Single named vector field in a Qdrant collection.

    Field names map directly to the Qdrant REST API, so
    ``model_dump(exclude_none=True)`` produces a valid API payload.
    """

    size: int = Field(ge=1, description="Vector dimension")
    distance: str = Field(default="Cosine", pattern=r"^(Dot|Cosine|Euclid)$")
    multivector_config: dict[str, str] | None = Field(default=None)
    on_disk: bool | None = Field(
        default=None,
        description="Store vectors in memory-mapped files instead of RAM. "
        "None defers to Qdrant's collection-level default.",
    )


class QdrantSparseConfig(BaseModel):
    """Sparse vector configuration for a Qdrant collection.

    Each collection has at most one sparse vector.  The ``name`` field
    controls the Qdrant named-vector key (defaults to ``sparse``), and
    ``full_scan_threshold`` controls when the engine switches from a
    brute-force scan to an indexed search.
    """

    name: str = Field(default="sparse")
    full_scan_threshold: int = Field(
        default=100_000,
        ge=1,
        description="Switch from full scan to indexed search above this many vectors.",
    )


class QdrantCollectionSchema(BaseModel):
    """Complete vector schema for a single Qdrant collection.

    Consumed by ``qdrant-init`` and ``nohiki-qdrant-client`` to create
    collections and derive vector names at runtime.

    Role fields (``primary_dense_name``, ``colbert_name``) explicitly declare
    which named vector serves each purpose, avoiding magic string matching.
    """

    vectors: dict[str, QdrantVectorDefinition] = Field(
        description="Named vector definitions keyed by Qdrant vector name",
    )
    sparse: QdrantSparseConfig | None = Field(
        default=None,
        description="Sparse vector config.  Omit or set to None for collections that do not use sparse vectors.",
    )
    primary_dense_name: str = Field(
        description="Key in ``vectors`` used for primary dense retrieval",
    )
    colbert_name: str | None = Field(
        default=None,
        description="Key in ``vectors`` used for ColBERT MaxSim reranking",
    )

    @model_validator(mode="after")
    def _validate_role_references(self) -> Self:
        """Ensure role names reference existing vector definitions."""
        if self.primary_dense_name not in self.vectors:
            msg = f"primary_dense_name '{self.primary_dense_name}' not found in vectors: {sorted(self.vectors)}"
            raise ValueError(msg)
        if self.colbert_name is not None:
            if self.colbert_name not in self.vectors:
                msg = f"colbert_name '{self.colbert_name}' not found in vectors: {sorted(self.vectors)}"
                raise ValueError(msg)
            defn = self.vectors[self.colbert_name]
            if not defn.multivector_config:
                msg = f"colbert_name '{self.colbert_name}' must have multivector_config"
                raise ValueError(msg)
        return self


class CollectionConfig(BaseModel):
    """Per-entity collection configuration with independent versioning.

    Incrementing ``version`` creates a new Qdrant collection while the old
    one remains available for zero-downtime migration via alias swap.
    Collection naming: ``{entity}_{version}`` (e.g. ``jobs_v1``).
    """

    version: str = Field(pattern=r"^v\d+$")
    description: str | None = Field(default=None)
    qdrant: QdrantCollectionSchema


class CollectionsConfig(BaseModel):
    """Top-level container for all entity collection configurations.

    Each entity can evolve independently: changing an embedding model
    only requires incrementing the version for affected collections.
    """

    jobs: CollectionConfig
    profiles: CollectionConfig
    skills: CollectionConfig
    occupations: CollectionConfig

    def items(self) -> Iterator[tuple[str, CollectionConfig]]:
        """Yield ``(entity_type, config)`` pairs for all collections."""
        for field_name in self.model_fields:
            yield field_name, getattr(self, field_name)

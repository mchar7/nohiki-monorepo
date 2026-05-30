"""Qdrant vector database feature configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nohiki_scaffold.core.exceptions import ValidationError

from ._validation import validate_qdrant_entity

QdrantEntity = Literal["jobs", "profiles", "skills", "occupations"]


@dataclass(frozen=True, slots=True)
class QdrantOptions:
    """Qdrant vector database feature flags and parameters.

    When ``enabled=True``, ``collection_entity`` must be one of the canonical
    entity types registered in the nohiki ML manifest.
    """

    enabled: bool = False
    collection_entity: QdrantEntity | None = None

    def __post_init__(self) -> None:
        """Require collection_entity when enabled; forbid it when disabled."""
        if self.enabled:
            if self.collection_entity is None:
                msg = "qdrant.collection_entity is required when qdrant.enabled=True"
                raise ValidationError(msg)
            validate_qdrant_entity(self.collection_entity)
        elif self.collection_entity is not None:
            msg = "qdrant.collection_entity requires qdrant.enabled=True"
            raise ValidationError(msg)


__all__ = ["QdrantEntity", "QdrantOptions"]

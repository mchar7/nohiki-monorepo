"""Immutable value objects representing skill graph seed data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillRecord:
    """A single skill to be seeded into the skill graph."""

    normalized_text: str
    display_name: str | None
    skill_type: str
    reuse_level: str | None
    category: str | None
    subcategory: str | None
    description: str | None
    external_id: str | None
    external_uri: str | None


@dataclass(frozen=True)
class AliasRecord:
    """A mapping from alias text to a canonical skill."""

    alias_text: str
    skill_normalized_text: str
    context_hint: str | None
    confidence: float


@dataclass(frozen=True)
class RelationshipRecord:
    """A directed relationship between two skills."""

    source_normalized_text: str
    target_normalized_text: str
    relationship_type: str
    strength: float
    bidirectional: bool


@dataclass(frozen=True)
class OccupationSkillRecord:
    """An occupation-to-skill relationship from a seed source."""

    occupation_code: str
    occupation_label: str
    skill_normalized_text: str
    relation_type: str
    source_metadata: dict[str, str]


@dataclass(frozen=True)
class OccupationRecord:
    """An ESCO occupation entity for embedding and job title inference."""

    occupation_code: str
    preferred_label: str
    description: str | None
    alt_labels: list[str]
    isco_group_code: str | None
    occupation_type: str

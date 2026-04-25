"""Protocol defining the contract all skill data sources must satisfy."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.strategies import ConflictStrategy, SourceAuthority


@runtime_checkable
class SkillDataSource(Protocol):
    """Source of skill graph seed data.

    All methods returning iterators support streaming large datasets without
    loading everything into memory. Methods have default no-op implementations
    so sources that don't provide certain data types need not override them.
    """

    @property
    def source_name(self) -> str:
        """Identifier used in provenance records (e.g., 'tabiya', 'curated')."""
        ...

    @property
    def source_version(self) -> str:
        """Version string for this data release (e.g., 'v1.0.0', '2024-q4')."""
        ...

    @property
    def authority(self) -> SourceAuthority:
        """Authority ranking; higher value wins conflict resolution."""
        ...

    @property
    def conflict_strategy(self) -> ConflictStrategy:
        """How this source handles conflicts with existing data."""
        ...

    def iter_skills(self) -> Iterator[SkillRecord]:
        """Yield skill records from this source."""
        return iter([])

    def iter_aliases(self) -> Iterator[AliasRecord]:
        """Yield alias records from this source."""
        return iter([])

    def iter_relationships(self) -> Iterator[RelationshipRecord]:
        """Yield relationship records from this source."""
        return iter([])

    def iter_occupation_relations(self) -> Iterator[OccupationSkillRecord]:
        """Yield occupation-skill relation records from this source."""
        return iter([])

    def iter_occupations(self) -> Iterator[OccupationRecord]:
        """Yield occupation records from this source."""
        return iter([])

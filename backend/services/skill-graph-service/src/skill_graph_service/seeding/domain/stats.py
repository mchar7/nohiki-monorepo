"""Result and statistics types for seeding runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SeedStats:
    """Counts of rows affected during a single seeding run."""

    skills_added: int = 0
    skills_updated: int = 0
    aliases_added: int = 0
    relationships_added: int = 0
    occupation_relations_added: int = 0
    occupations_added: int = 0
    error_count: int = 0

    def __add__(self, other: SeedStats) -> SeedStats:
        """Combine two SeedStats by summing all fields."""
        return SeedStats(
            skills_added=self.skills_added + other.skills_added,
            skills_updated=self.skills_updated + other.skills_updated,
            aliases_added=self.aliases_added + other.aliases_added,
            relationships_added=self.relationships_added + other.relationships_added,
            occupation_relations_added=self.occupation_relations_added + other.occupation_relations_added,
            occupations_added=self.occupations_added + other.occupations_added,
            error_count=self.error_count + other.error_count,
        )


@dataclass(frozen=True)
class SeedResult:
    """Complete result of seeding from a single source."""

    source_name: str
    source_version: str
    stats: SeedStats = field(default_factory=SeedStats)
    completed_at: datetime = field(default_factory=datetime.now)

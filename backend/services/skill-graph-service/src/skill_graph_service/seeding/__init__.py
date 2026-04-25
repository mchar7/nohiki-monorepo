"""Skill graph seeding module: owns all seeding logic within the service."""

from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.stats import SeedResult, SeedStats
from skill_graph_service.seeding.domain.strategies import ConflictStrategy, SourceAuthority
from skill_graph_service.seeding.normalizer import normalize_skill_text
from skill_graph_service.seeding.protocols.source import SkillDataSource
from skill_graph_service.seeding.seeder import SkillGraphSeeder
from skill_graph_service.seeding.sources.tabiya import TabiyaDataSource

__all__ = [
    "AliasRecord",
    "ConflictStrategy",
    "OccupationRecord",
    "OccupationSkillRecord",
    "RelationshipRecord",
    "SeedResult",
    "SeedStats",
    "SkillDataSource",
    "SkillGraphSeeder",
    "SkillRecord",
    "SourceAuthority",
    "TabiyaDataSource",
    "normalize_skill_text",
]

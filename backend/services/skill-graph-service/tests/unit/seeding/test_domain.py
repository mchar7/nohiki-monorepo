"""Tests for seeding domain models."""

from __future__ import annotations

from datetime import datetime

from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.stats import SeedResult, SeedStats
from skill_graph_service.seeding.domain.strategies import ConflictStrategy, SourceAuthority


class TestSkillRecord:
    """Tests for SkillRecord dataclass."""

    def test_create_with_all_fields(self) -> None:
        """SkillRecord can be created with all fields."""
        record = SkillRecord(
            normalized_text="python programming",
            display_name="Python Programming",
            skill_type="skill",
            reuse_level="cross-sector",
            category="programming",
            subcategory="languages",
            description="Programming in Python",
            external_id="ext123",
            external_uri="http://example.com/skill/123",
        )
        assert record.normalized_text == "python programming"
        assert record.display_name == "Python Programming"
        assert record.skill_type == "skill"
        assert record.reuse_level == "cross-sector"
        assert record.category == "programming"
        assert record.subcategory == "languages"
        assert record.description == "Programming in Python"
        assert record.external_id == "ext123"
        assert record.external_uri == "http://example.com/skill/123"

    def test_nullable_fields(self) -> None:
        """SkillRecord nullable fields can be None."""
        record = SkillRecord(
            normalized_text="test",
            display_name=None,
            skill_type="skill",
            reuse_level=None,
            category=None,
            subcategory=None,
            description=None,
            external_id=None,
            external_uri=None,
        )
        assert record.display_name is None
        assert record.reuse_level is None
        assert record.category is None

    def test_is_frozen(self) -> None:
        """SkillRecord is frozen dataclass."""
        assert SkillRecord.__dataclass_params__.frozen


class TestAliasRecord:
    """Tests for AliasRecord dataclass."""

    def test_create_with_all_fields(self) -> None:
        """AliasRecord can be created with all fields."""
        record = AliasRecord(
            alias_text="py",
            skill_normalized_text="python programming",
            context_hint="programming",
            confidence=0.95,
        )
        assert record.alias_text == "py"
        assert record.skill_normalized_text == "python programming"
        assert record.context_hint == "programming"
        assert record.confidence == 0.95

    def test_context_hint_nullable(self) -> None:
        """AliasRecord context_hint can be None."""
        record = AliasRecord(
            alias_text="py",
            skill_normalized_text="python",
            context_hint=None,
            confidence=1.0,
        )
        assert record.context_hint is None

    def test_is_frozen(self) -> None:
        """AliasRecord is frozen dataclass."""
        assert AliasRecord.__dataclass_params__.frozen


class TestRelationshipRecord:
    """Tests for RelationshipRecord dataclass."""

    def test_create_with_all_fields(self) -> None:
        """RelationshipRecord can be created with all fields."""
        record = RelationshipRecord(
            source_normalized_text="python",
            target_normalized_text="programming",
            relationship_type="related",
            strength=0.8,
            bidirectional=True,
        )
        assert record.source_normalized_text == "python"
        assert record.target_normalized_text == "programming"
        assert record.relationship_type == "related"
        assert record.strength == 0.8
        assert record.bidirectional is True

    def test_unidirectional(self) -> None:
        """RelationshipRecord can be unidirectional."""
        record = RelationshipRecord(
            source_normalized_text="python",
            target_normalized_text="programming",
            relationship_type="broader",
            strength=1.0,
            bidirectional=False,
        )
        assert record.bidirectional is False


class TestOccupationSkillRecord:
    """Tests for OccupationSkillRecord dataclass."""

    def test_create_with_all_fields(self) -> None:
        """OccupationSkillRecord can be created with all fields."""
        record = OccupationSkillRecord(
            occupation_code="2512.1",
            occupation_label="Software Developer",
            skill_normalized_text="python programming",
            relation_type="optional",
            source_metadata={"weight": "0.9"},
        )
        assert record.occupation_code == "2512.1"
        assert record.occupation_label == "Software Developer"
        assert record.skill_normalized_text == "python programming"
        assert record.relation_type == "optional"
        assert record.source_metadata == {"weight": "0.9"}

    def test_empty_metadata(self) -> None:
        """OccupationSkillRecord can have empty metadata."""
        record = OccupationSkillRecord(
            occupation_code="2512.1",
            occupation_label="Developer",
            skill_normalized_text="python",
            relation_type="essential",
            source_metadata={},
        )
        assert record.source_metadata == {}


class TestOccupationRecord:
    """Tests for OccupationRecord dataclass."""

    def test_create_with_all_fields(self) -> None:
        """OccupationRecord can be created with all fields."""
        record = OccupationRecord(
            occupation_code="2512.1",
            preferred_label="Software Developer",
            description="Develops software applications",
            alt_labels=["Programmer", "Coder"],
            isco_group_code="2512",
            occupation_type="esco",
        )
        assert record.occupation_code == "2512.1"
        assert record.preferred_label == "Software Developer"
        assert record.description == "Develops software applications"
        assert record.alt_labels == ["Programmer", "Coder"]
        assert record.isco_group_code == "2512"
        assert record.occupation_type == "esco"

    def test_nullable_fields(self) -> None:
        """OccupationRecord nullable fields can be None."""
        record = OccupationRecord(
            occupation_code="2512.1",
            preferred_label="Developer",
            description=None,
            alt_labels=[],
            isco_group_code=None,
            occupation_type="esco",
        )
        assert record.description is None
        assert record.isco_group_code is None
        assert record.alt_labels == []


class TestSeedStats:
    """Tests for SeedStats dataclass."""

    def test_default_values(self) -> None:
        """SeedStats has zero defaults for all counters."""
        stats = SeedStats()
        assert stats.skills_added == 0
        assert stats.skills_updated == 0
        assert stats.aliases_added == 0
        assert stats.relationships_added == 0
        assert stats.occupation_relations_added == 0
        assert stats.occupations_added == 0
        assert stats.error_count == 0

    def test_create_with_values(self) -> None:
        """SeedStats can be created with specific values."""
        stats = SeedStats(
            skills_added=100,
            skills_updated=10,
            aliases_added=50,
            relationships_added=25,
            occupation_relations_added=200,
            occupations_added=30,
            error_count=5,
        )
        assert stats.skills_added == 100
        assert stats.skills_updated == 10
        assert stats.aliases_added == 50
        assert stats.relationships_added == 25
        assert stats.occupation_relations_added == 200
        assert stats.occupations_added == 30
        assert stats.error_count == 5

    def test_add_combines_values(self) -> None:
        """SeedStats.__add__ combines values from two stats."""
        stats1 = SeedStats(skills_added=10, aliases_added=5)
        stats2 = SeedStats(skills_added=20, relationships_added=15)
        combined = stats1 + stats2
        assert combined.skills_added == 30
        assert combined.aliases_added == 5
        assert combined.relationships_added == 15

    def test_add_is_immutable(self) -> None:
        """SeedStats.__add__ returns new instance, doesn't modify original."""
        stats1 = SeedStats(skills_added=10)
        stats2 = SeedStats(skills_added=20)
        combined = stats1 + stats2
        assert stats1.skills_added == 10
        assert stats2.skills_added == 20
        assert combined.skills_added == 30


class TestSeedResult:
    """Tests for SeedResult dataclass."""

    def test_create_with_required_fields(self) -> None:
        """SeedResult can be created with required fields only."""
        result = SeedResult(
            source_name="tabiya",
            source_version="v1.2.0",
        )
        assert result.source_name == "tabiya"
        assert result.source_version == "v1.2.0"
        assert result.stats.skills_added == 0
        assert isinstance(result.completed_at, datetime)

    def test_create_with_all_fields(self) -> None:
        """SeedResult can be created with all fields."""
        now = datetime.now()
        stats = SeedStats(skills_added=100)
        result = SeedResult(
            source_name="tabiya",
            source_version="v1.2.0",
            stats=stats,
            completed_at=now,
        )
        assert result.source_name == "tabiya"
        assert result.source_version == "v1.2.0"
        assert result.stats.skills_added == 100
        assert result.completed_at == now


class TestConflictStrategy:
    """Tests for ConflictStrategy enum."""

    def test_skip_value(self) -> None:
        """ConflictStrategy.SKIP has expected value."""
        assert ConflictStrategy.SKIP.value == "skip"

    def test_upsert_value(self) -> None:
        """ConflictStrategy.UPSERT has expected value."""
        assert ConflictStrategy.UPSERT.value == "upsert"

    def test_version_gate_update_value(self) -> None:
        """ConflictStrategy.VERSION_GATE_UPDATE has expected value."""
        assert ConflictStrategy.VERSION_GATE_UPDATE.value == "version_gate_update"

    def test_all_strategies_exist(self) -> None:
        """All expected strategies exist."""
        strategies = {s.value for s in ConflictStrategy}
        assert strategies == {"skip", "upsert", "version_gate_update"}


class TestSourceAuthority:
    """Tests for SourceAuthority enum."""

    def test_curated_highest(self) -> None:
        """SourceAuthority.CURATED has highest value."""
        assert SourceAuthority.CURATED.value == 3

    def test_tabiya_second(self) -> None:
        """SourceAuthority.TABIYA has second highest value."""
        assert SourceAuthority.TABIYA.value == 2

    def test_nohiki_learned_lowest(self) -> None:
        """SourceAuthority.NOHIKI_LEARNED has lowest value."""
        assert SourceAuthority.NOHIKI_LEARNED.value == 1

    def test_ordering(self) -> None:
        """SourceAuthority values are ordered as expected."""
        assert SourceAuthority.CURATED.value > SourceAuthority.TABIYA.value
        assert SourceAuthority.TABIYA.value > SourceAuthority.NOHIKI_LEARNED.value

    def test_is_int_enum(self) -> None:
        """SourceAuthority is an IntEnum for numeric comparison."""
        assert SourceAuthority.CURATED > SourceAuthority.TABIYA
        assert SourceAuthority.TABIYA > SourceAuthority.NOHIKI_LEARNED

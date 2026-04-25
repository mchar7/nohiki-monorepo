"""Tests for SkillGraphSeeder."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.stats import SeedStats
from skill_graph_service.seeding.domain.strategies import ConflictStrategy, SourceAuthority
from skill_graph_service.seeding.seeder import SkillGraphSeeder, _batched


class MockSkillDataSource:
    """Mock implementation of SkillDataSource protocol for testing."""

    def __init__(
        self,
        *,
        skills: list[SkillRecord] | None = None,
        aliases: list[AliasRecord] | None = None,
        relationships: list[RelationshipRecord] | None = None,
        occupation_relations: list[OccupationSkillRecord] | None = None,
        occupations: list[OccupationRecord] | None = None,
        source_name: str = "test_source",
        source_version: str = "1.0.0",
        authority: SourceAuthority = SourceAuthority.TABIYA,
        conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP,
    ) -> None:
        self._skills = skills or []
        self._aliases = aliases or []
        self._relationships = relationships or []
        self._occupation_relations = occupation_relations or []
        self._occupations = occupations or []
        self._source_name = source_name
        self._source_version = source_version
        self._authority = authority
        self._conflict_strategy = conflict_strategy

    @property
    def source_name(self) -> str:
        return self._source_name

    @property
    def source_version(self) -> str:
        return self._source_version

    @property
    def authority(self) -> SourceAuthority:
        return self._authority

    @property
    def conflict_strategy(self) -> ConflictStrategy:
        return self._conflict_strategy

    def iter_skills(self) -> Iterator[SkillRecord]:
        yield from self._skills

    def iter_aliases(self) -> Iterator[AliasRecord]:
        yield from self._aliases

    def iter_relationships(self) -> Iterator[RelationshipRecord]:
        yield from self._relationships

    def iter_occupation_relations(self) -> Iterator[OccupationSkillRecord]:
        yield from self._occupation_relations

    def iter_occupations(self) -> Iterator[OccupationRecord]:
        yield from self._occupations


def _make_skill_record(normalized_text: str) -> SkillRecord:
    """Create a SkillRecord for testing."""
    return SkillRecord(
        normalized_text=normalized_text,
        display_name=normalized_text.title(),
        skill_type="specialized",
        reuse_level="cross-sector",
        category="Test",
        subcategory="Testing",
        description="Test skill",
        external_id=f"ext-{normalized_text}",
        external_uri=f"http://example.com/{normalized_text}",
    )


def _make_alias_record(alias_text: str, skill_text: str) -> AliasRecord:
    """Create an AliasRecord for testing."""
    return AliasRecord(
        alias_text=alias_text,
        skill_normalized_text=skill_text,
        context_hint=None,
        confidence=0.95,
    )


def _make_relationship_record(source: str, target: str) -> RelationshipRecord:
    """Create a RelationshipRecord for testing."""
    return RelationshipRecord(
        source_normalized_text=source,
        target_normalized_text=target,
        relationship_type="related",
        strength=0.8,
        bidirectional=False,
    )


def _make_occupation_skill_record(occ_code: str, skill_text: str) -> OccupationSkillRecord:
    """Create an OccupationSkillRecord for testing."""
    return OccupationSkillRecord(
        occupation_code=occ_code,
        occupation_label="Test Occupation",
        skill_normalized_text=skill_text,
        relation_type="essential",
        source_metadata={},
    )


def _make_occupation_record(occ_code: str) -> OccupationRecord:
    """Create an OccupationRecord for testing."""
    return OccupationRecord(
        occupation_code=occ_code,
        preferred_label="Test Occupation",
        description="Test description",
        alt_labels=["Alias 1"],
        isco_group_code="2512",
        occupation_type="escooccupation",
    )


class TestBatched:
    """Tests for _batched helper function."""

    def test_batches_items(self) -> None:
        """_batched groups items into batches of specified size."""
        items = [1, 2, 3, 4, 5]
        batches = list(_batched(items, 2))
        assert batches == [[1, 2], [3, 4], [5]]

    def test_single_batch(self) -> None:
        """_batched returns single batch when items fit."""
        items = [1, 2, 3]
        batches = list(_batched(items, 10))
        assert batches == [[1, 2, 3]]

    def test_empty_input(self) -> None:
        """_batched yields nothing for empty input."""
        batches = list(_batched([], 10))
        assert batches == []

    def test_exact_batch_size(self) -> None:
        """_batched handles exact batch size division."""
        items = [1, 2, 3, 4]
        batches = list(_batched(items, 2))
        assert batches == [[1, 2], [3, 4]]


class TestSkillGraphSeederInit:
    """Tests for SkillGraphSeeder initialization."""

    def test_init_with_sources_and_engine(self) -> None:
        """SkillGraphSeeder can be initialized with sources and engine."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        assert seeder._engine is mock_engine
        assert seeder._batch_size == 1000
        assert len(seeder._sources) == 1

    def test_init_with_custom_batch_size(self) -> None:
        """SkillGraphSeeder accepts custom batch size."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=500)
        assert seeder._batch_size == 500

    def test_init_with_multiple_sources(self) -> None:
        """SkillGraphSeeder accepts multiple sources."""
        mock_engine = MagicMock()
        source1 = MockSkillDataSource(source_name="source1")
        source2 = MockSkillDataSource(source_name="source2")
        seeder = SkillGraphSeeder(sources=[source1, source2], engine=mock_engine)
        assert len(seeder._sources) == 2


class TestSkillGraphSeederSeed:
    """Tests for SkillGraphSeeder.seed method."""

    @pytest.mark.asyncio
    async def test_seed_empty_source(self) -> None:
        """Seed handles empty source gracefully."""
        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=AsyncMock())
        mock_engine.connect = MagicMock(return_value=AsyncMock())

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        with (
            patch.object(seeder, "_start_batch_record", new_callable=AsyncMock) as mock_start,
            patch.object(seeder, "_complete_batch_record", new_callable=AsyncMock),
            patch.object(seeder, "_load_skill_ids_by_texts", new_callable=AsyncMock) as mock_load,
        ):
            mock_start.return_value = uuid.uuid4()
            mock_load.return_value = {}
            results = await seeder.seed()

        assert len(results) == 1
        assert results[0].source_name == "test_source"
        assert results[0].source_version == "1.0.0"
        assert results[0].stats.skills_added == 0

    @pytest.mark.asyncio
    async def test_seed_with_skills(self) -> None:
        """Seed processes skills from source."""
        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=AsyncMock())
        mock_engine.connect = MagicMock(return_value=AsyncMock())

        source = MockSkillDataSource(skills=[_make_skill_record("python")])
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        batch_id = uuid.uuid4()
        with (
            patch.object(seeder, "_start_batch_record", new_callable=AsyncMock) as mock_start,
            patch.object(seeder, "_complete_batch_record", new_callable=AsyncMock),
            patch.object(seeder, "_insert_skills", new_callable=AsyncMock) as mock_insert,
            patch.object(seeder, "_load_skill_ids_by_texts", new_callable=AsyncMock) as mock_load,
            patch.object(seeder, "_upsert_provenance", new_callable=AsyncMock),
        ):
            mock_start.return_value = batch_id
            mock_insert.return_value = (SeedStats(skills_added=1), {"python"})
            mock_load.return_value = {"python": uuid.uuid4()}
            results = await seeder.seed()

        assert len(results) == 1
        assert results[0].stats.skills_added == 1
        mock_insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_seed_multiple_sources(self) -> None:
        """Seed processes multiple sources in order."""
        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=AsyncMock())
        mock_engine.connect = MagicMock(return_value=AsyncMock())

        source1 = MockSkillDataSource(source_name="source1")
        source2 = MockSkillDataSource(source_name="source2")
        seeder = SkillGraphSeeder(sources=[source1, source2], engine=mock_engine)

        with (
            patch.object(seeder, "_start_batch_record", new_callable=AsyncMock) as mock_start,
            patch.object(seeder, "_complete_batch_record", new_callable=AsyncMock),
            patch.object(seeder, "_load_skill_ids_by_texts", new_callable=AsyncMock) as mock_load,
        ):
            mock_start.return_value = uuid.uuid4()
            mock_load.return_value = {}
            results = await seeder.seed()

        assert len(results) == 2
        assert results[0].source_name == "source1"
        assert results[1].source_name == "source2"


class TestSkillGraphSeederBatchRecord:
    """Tests for batch record management."""

    @pytest.mark.asyncio
    async def test_start_batch_record(self) -> None:
        """_start_batch_record inserts record and returns ID."""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        expected_id = uuid.uuid4()
        mock_result.scalar_one.return_value = expected_id
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        result = await seeder._start_batch_record(source)

        assert result == expected_id
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_batch_record(self) -> None:
        """_complete_batch_record updates record with stats."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        batch_id = uuid.uuid4()
        stats = SeedStats(skills_added=10)

        await seeder._complete_batch_record(batch_id, stats, "completed")

        mock_conn.execute.assert_called_once()


class TestSkillGraphSeederLoadSkillIds:
    """Tests for _load_skill_ids_by_texts method."""

    @pytest.mark.asyncio
    async def test_empty_texts_returns_empty(self) -> None:
        """_load_skill_ids_by_texts returns empty dict for empty input."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        result = await seeder._load_skill_ids_by_texts(set())

        assert result == {}

    @pytest.mark.asyncio
    async def test_loads_ids_from_db(self) -> None:
        """_load_skill_ids_by_texts queries database for skill IDs."""
        skill_id = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.normalized_text = "python"
        mock_row.id = skill_id

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        result = await seeder._load_skill_ids_by_texts({"python"})

        assert result == {"python": skill_id}


class TestSkillGraphSeederInsertSkills:
    """Tests for _insert_skills method."""

    @pytest.mark.asyncio
    async def test_insert_skills_batch(self) -> None:
        """_insert_skills processes skills in batches."""
        mock_engine = MagicMock()
        source = MockSkillDataSource(conflict_strategy=ConflictStrategy.SKIP)
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        skills = [_make_skill_record("python"), _make_skill_record("javascript")]

        with patch.object(seeder, "_insert_skill_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = ({"python"}, 1, 0)
            stats, _ = await seeder._insert_skills(source, skills)

        assert mock_batch.call_count == 2
        assert stats.skills_added == 2

    @pytest.mark.asyncio
    async def test_insert_skills_handles_errors(self) -> None:
        """_insert_skills counts errors on batch failures."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        skills = [_make_skill_record("python")]

        with patch.object(seeder, "_insert_skill_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.side_effect = Exception("DB error")
            stats, _ = await seeder._insert_skills(source, skills)

        assert stats.error_count == 1
        assert stats.skills_added == 0


class TestSkillGraphSeederInsertAliases:
    """Tests for _insert_aliases method."""

    @pytest.mark.asyncio
    async def test_insert_aliases_batch(self) -> None:
        """_insert_aliases processes aliases in batches."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        aliases = [_make_alias_record("py", "python")]
        id_map = {"python": uuid.uuid4()}

        with patch.object(seeder, "_insert_alias_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = 1
            stats = await seeder._insert_aliases(source, aliases, id_map)

        assert stats.aliases_added == 1


class TestSkillGraphSeederInsertRelationships:
    """Tests for _insert_relationships method."""

    @pytest.mark.asyncio
    async def test_insert_relationships_batch(self) -> None:
        """_insert_relationships processes relationships in batches."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        relationships = [_make_relationship_record("python", "programming")]
        id_map = {"python": uuid.uuid4(), "programming": uuid.uuid4()}

        with patch.object(seeder, "_insert_relationship_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = 1
            stats = await seeder._insert_relationships(source, relationships, id_map)

        assert stats.relationships_added == 1


class TestSkillGraphSeederInsertOccupationRelations:
    """Tests for _insert_occupation_relations method."""

    @pytest.mark.asyncio
    async def test_insert_occupation_relations_batch(self) -> None:
        """_insert_occupation_relations processes relations in batches."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        relations = [_make_occupation_skill_record("2512.1", "python")]
        id_map = {"python": uuid.uuid4()}

        with patch.object(seeder, "_insert_occupation_relation_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = 1
            stats = await seeder._insert_occupation_relations(source, relations, id_map)

        assert stats.occupation_relations_added == 1


class TestSkillGraphSeederInsertOccupations:
    """Tests for _insert_occupations method."""

    @pytest.mark.asyncio
    async def test_insert_occupations_batch(self) -> None:
        """_insert_occupations processes occupations in batches."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        occupations = [_make_occupation_record("2512.1")]

        with patch.object(seeder, "_insert_occupation_node_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = 1
            stats = await seeder._insert_occupations(source, occupations)

        assert stats.occupations_added == 1

    @pytest.mark.asyncio
    async def test_insert_occupations_handles_errors(self) -> None:
        """_insert_occupations counts errors on batch failures."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        occupations = [_make_occupation_record("2512.1")]

        with patch.object(seeder, "_insert_occupation_node_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.side_effect = Exception("DB error")
            stats = await seeder._insert_occupations(source, occupations)

        assert stats.error_count == 1
        assert stats.occupations_added == 0


class TestSkillGraphSeederInsertSkillBatch:
    """Tests for _insert_skill_batch method."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_skills(self) -> None:
        """_insert_skill_batch returns empty set for empty input."""
        mock_conn = AsyncMock()
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        texts, added, updated = await seeder._insert_skill_batch(source, [])

        assert texts == set()
        assert added == 0
        assert updated == 0

    @pytest.mark.asyncio
    async def test_skip_strategy_inserts(self) -> None:
        """_insert_skill_batch with SKIP strategy uses on_conflict_do_nothing."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource(conflict_strategy=ConflictStrategy.SKIP)
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        skills = [_make_skill_record("python")]

        texts, added, updated = await seeder._insert_skill_batch(source, skills)

        assert "python" in texts
        assert added == 1
        assert updated == 0
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_strategy_inserts(self) -> None:
        """_insert_skill_batch with UPSERT strategy uses on_conflict_do_update."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource(conflict_strategy=ConflictStrategy.UPSERT)
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        skills = [_make_skill_record("python")]

        texts, added, _updated = await seeder._insert_skill_batch(source, skills)

        assert "python" in texts
        assert added == 1
        mock_conn.execute.assert_called_once()


class TestSkillGraphSeederInsertAliasBatch:
    """Tests for _insert_alias_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_aliases(self) -> None:
        """_insert_alias_batch returns 0 for empty input."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        count = await seeder._insert_alias_batch(source, [], {})

        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_aliases_without_skill_id(self) -> None:
        """_insert_alias_batch skips aliases without matching skill ID."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        aliases = [_make_alias_record("py", "python")]
        count = await seeder._insert_alias_batch(source, aliases, {})

        assert count == 0

    @pytest.mark.asyncio
    async def test_inserts_valid_aliases(self) -> None:
        """_insert_alias_batch inserts aliases with matching skill IDs."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource(conflict_strategy=ConflictStrategy.SKIP)
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        aliases = [_make_alias_record("py", "python")]
        id_map = {"python": uuid.uuid4()}

        count = await seeder._insert_alias_batch(source, aliases, id_map)

        assert count == 1


class TestSkillGraphSeederInsertRelationshipBatch:
    """Tests for _insert_relationship_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_relationships(self) -> None:
        """_insert_relationship_batch returns 0 for empty input."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        count = await seeder._insert_relationship_batch(source, [], {})

        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_relationships_without_skill_ids(self) -> None:
        """_insert_relationship_batch skips relationships without matching IDs."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        relationships = [_make_relationship_record("python", "programming")]
        count = await seeder._insert_relationship_batch(source, relationships, {})

        assert count == 0

    @pytest.mark.asyncio
    async def test_inserts_valid_relationships(self) -> None:
        """_insert_relationship_batch inserts relationships with matching IDs."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        relationships = [_make_relationship_record("python", "programming")]
        id_map = {"python": uuid.uuid4(), "programming": uuid.uuid4()}

        count = await seeder._insert_relationship_batch(source, relationships, id_map)

        assert count == 1


class TestSkillGraphSeederInsertOccupationRelationBatch:
    """Tests for _insert_occupation_relation_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_relations(self) -> None:
        """_insert_occupation_relation_batch returns 0 for empty input."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        count = await seeder._insert_occupation_relation_batch(source, [], {})

        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_relations_without_skill_id(self) -> None:
        """_insert_occupation_relation_batch skips relations without skill ID."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        relations = [_make_occupation_skill_record("2512.1", "python")]
        count = await seeder._insert_occupation_relation_batch(source, relations, {})

        assert count == 0

    @pytest.mark.asyncio
    async def test_inserts_valid_relations(self) -> None:
        """_insert_occupation_relation_batch inserts relations with skill IDs."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        relations = [_make_occupation_skill_record("2512.1", "python")]
        id_map = {"python": uuid.uuid4()}

        count = await seeder._insert_occupation_relation_batch(source, relations, id_map)

        assert count == 1


class TestSkillGraphSeederInsertOccupationNodeBatch:
    """Tests for _insert_occupation_node_batch method."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_occupations(self) -> None:
        """_insert_occupation_node_batch returns 0 for empty input."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)

        count = await seeder._insert_occupation_node_batch(source, [])

        assert count == 0

    @pytest.mark.asyncio
    async def test_inserts_occupations(self) -> None:
        """_insert_occupation_node_batch inserts occupation records."""
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        occupations = [_make_occupation_record("2512.1")]

        count = await seeder._insert_occupation_node_batch(source, occupations)

        assert count == 1


class TestSkillGraphSeederUpsertProvenance:
    """Tests for _upsert_provenance method."""

    @pytest.mark.asyncio
    async def test_upserts_provenance_records(self) -> None:
        """_upsert_provenance inserts provenance for seeded skills."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_engine = MagicMock()
        mock_engine.begin = MagicMock(return_value=mock_context)

        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        skills = [_make_skill_record("python")]
        id_map = {"python": uuid.uuid4()}

        await seeder._upsert_provenance(source, skills, id_map)

        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_skills_not_in_id_map(self) -> None:
        """_upsert_provenance skips skills without matching IDs."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine)
        skills = [_make_skill_record("python")]

        await seeder._upsert_provenance(source, skills, {})


class TestSkillGraphSeederInsertRelationshipsErrors:
    """Tests for _insert_relationships error handling."""

    @pytest.mark.asyncio
    async def test_handles_batch_errors(self) -> None:
        """_insert_relationships counts errors on batch failures."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        relationships = [_make_relationship_record("python", "programming")]
        id_map = {"python": uuid.uuid4(), "programming": uuid.uuid4()}

        with patch.object(seeder, "_insert_relationship_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.side_effect = Exception("DB error")
            stats = await seeder._insert_relationships(source, relationships, id_map)

        assert stats.error_count == 1
        assert stats.relationships_added == 0


class TestSkillGraphSeederInsertOccupationRelationsErrors:
    """Tests for _insert_occupation_relations error handling."""

    @pytest.mark.asyncio
    async def test_handles_batch_errors(self) -> None:
        """_insert_occupation_relations counts errors on batch failures."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        relations = [_make_occupation_skill_record("2512.1", "python")]
        id_map = {"python": uuid.uuid4()}

        with patch.object(seeder, "_insert_occupation_relation_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.side_effect = Exception("DB error")
            stats = await seeder._insert_occupation_relations(source, relations, id_map)

        assert stats.error_count == 1
        assert stats.occupation_relations_added == 0


class TestSkillGraphSeederInsertAliasesErrors:
    """Tests for _insert_aliases error handling."""

    @pytest.mark.asyncio
    async def test_handles_batch_errors(self) -> None:
        """_insert_aliases counts errors on batch failures."""
        mock_engine = MagicMock()
        source = MockSkillDataSource()
        seeder = SkillGraphSeeder(sources=[source], engine=mock_engine, batch_size=1)
        aliases = [_make_alias_record("py", "python")]
        id_map = {"python": uuid.uuid4()}

        with patch.object(seeder, "_insert_alias_batch", new_callable=AsyncMock) as mock_batch:
            mock_batch.side_effect = Exception("DB error")
            stats = await seeder._insert_aliases(source, aliases, id_map)

        assert stats.error_count == 1
        assert stats.aliases_added == 0

"""Unit tests for skill-graph-service database repositories."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki_db_utils.testing import create_mock_session
from skill_graph_service.db.repositories import (
    SKILL_BATCH_SIZE,
    SkillRecord,
    _fetch_provenance_for_skill_ids,
    fetch_all_skills_for_embedding,
    stream_skills_with_provenance,
)

from ...helpers import MockAsyncIterator


class TestSkillRecord:
    """Tests for SkillRecord dataclass."""

    def test_init_with_all_fields(self) -> None:
        """Test SkillRecord initializes with all fields."""
        skill_id = uuid.uuid4()
        record = SkillRecord(
            id=skill_id,
            preferred_label="Python",
            description="A high-level programming language",
            alt_labels=["py", "python3"],
        )
        assert record.id == skill_id
        assert record.preferred_label == "Python"
        assert record.description == "A high-level programming language"
        assert record.alt_labels == ["py", "python3"]

    def test_init_defaults_alt_labels_to_empty(self) -> None:
        """Test SkillRecord defaults alt_labels to empty list."""
        skill_id = uuid.uuid4()
        record = SkillRecord(
            id=skill_id,
            preferred_label="Rust",
            description=None,
        )
        assert record.alt_labels == []

    def test_is_frozen(self) -> None:
        """Test SkillRecord is immutable (frozen dataclass)."""
        assert SkillRecord.__dataclass_params__.frozen

    def test_description_can_be_none(self) -> None:
        """Test SkillRecord accepts None description."""
        record = SkillRecord(
            id=uuid.uuid4(),
            preferred_label="TypeScript",
            description=None,
        )
        assert record.description is None


class TestFetchAllSkillsForEmbedding:
    """Tests for fetch_all_skills_for_embedding repository function."""

    def _make_skill_row(
        self,
        *,
        skill_id: uuid.UUID | None = None,
        normalized_text: str = "python",
        display_name: str | None = None,
        description: str | None = None,
    ) -> MagicMock:
        """Build a mock SQLAlchemy row representing a SkillNode projection."""
        row = MagicMock()
        row.id = skill_id or uuid.uuid4()
        row.normalized_text = normalized_text
        row.display_name = display_name
        row.description = description
        return row

    def _make_alias_row(self, canonical_skill_id: uuid.UUID, alias_text: str) -> MagicMock:
        """Build a mock SQLAlchemy row representing a SkillAlias projection."""
        row = MagicMock()
        row.canonical_skill_id = canonical_skill_id
        row.alias_text = alias_text
        return row

    def _make_db(
        self,
        skill_rows: list[MagicMock],
        alias_rows: list[MagicMock],
    ) -> AsyncMock:
        """Build a mock AsyncSession returning the given rows."""
        db = create_mock_session()
        skill_result = MagicMock()
        skill_result.all.return_value = skill_rows
        alias_result = MagicMock()
        alias_result.all.return_value = alias_rows
        db.execute = AsyncMock(side_effect=[skill_result, alias_result])
        return db

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_list(self) -> None:
        """Returns empty list immediately when no skills exist."""
        skill_result = MagicMock()
        skill_result.all.return_value = []
        db = create_mock_session()
        db.execute = AsyncMock(return_value=skill_result)

        result = await fetch_all_skills_for_embedding(db)

        assert result == []
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_skill_without_aliases_has_empty_alt_labels(self) -> None:
        """Skill with no aliases produces SkillRecord with empty alt_labels."""
        skill_id = uuid.uuid4()
        skill_row = self._make_skill_row(skill_id=skill_id, normalized_text="python")
        db = self._make_db(skill_rows=[skill_row], alias_rows=[])

        result = await fetch_all_skills_for_embedding(db)

        assert len(result) == 1
        assert result[0].id == skill_id
        assert result[0].alt_labels == []

    @pytest.mark.asyncio
    async def test_uses_display_name_when_available(self) -> None:
        """preferred_label is display_name when set on the skill node."""
        skill_id = uuid.uuid4()
        skill_row = self._make_skill_row(
            skill_id=skill_id,
            normalized_text="python",
            display_name="Python",
        )
        db = self._make_db(skill_rows=[skill_row], alias_rows=[])

        result = await fetch_all_skills_for_embedding(db)

        assert result[0].preferred_label == "Python"

    @pytest.mark.asyncio
    async def test_falls_back_to_normalized_text_when_no_display_name(self) -> None:
        """preferred_label is normalized_text when display_name is None."""
        skill_id = uuid.uuid4()
        skill_row = self._make_skill_row(
            skill_id=skill_id,
            normalized_text="machine learning",
            display_name=None,
        )
        db = self._make_db(skill_rows=[skill_row], alias_rows=[])

        result = await fetch_all_skills_for_embedding(db)

        assert result[0].preferred_label == "machine learning"

    @pytest.mark.asyncio
    async def test_description_propagated(self) -> None:
        """Description is carried through to SkillRecord."""
        skill_id = uuid.uuid4()
        skill_row = self._make_skill_row(
            skill_id=skill_id,
            normalized_text="rust",
            description="Systems programming language",
        )
        db = self._make_db(skill_rows=[skill_row], alias_rows=[])

        result = await fetch_all_skills_for_embedding(db)

        assert result[0].description == "Systems programming language"

    @pytest.mark.asyncio
    async def test_aliases_attached_to_correct_skill(self) -> None:
        """Aliases are grouped by skill_id and attached to the correct SkillRecord."""
        skill1_id = uuid.uuid4()
        skill2_id = uuid.uuid4()
        skill_rows = [
            self._make_skill_row(skill_id=skill1_id, normalized_text="python"),
            self._make_skill_row(skill_id=skill2_id, normalized_text="javascript"),
        ]
        alias_rows = [
            self._make_alias_row(skill1_id, "py"),
            self._make_alias_row(skill1_id, "python3"),
            self._make_alias_row(skill2_id, "js"),
        ]
        db = self._make_db(skill_rows=skill_rows, alias_rows=alias_rows)

        result = await fetch_all_skills_for_embedding(db)

        assert len(result) == 2
        python_record = next(r for r in result if r.id == skill1_id)
        js_record = next(r for r in result if r.id == skill2_id)
        assert set(python_record.alt_labels) == {"py", "python3"}
        assert js_record.alt_labels == ["js"]

    @pytest.mark.asyncio
    async def test_multiple_skills_returned_in_order(self) -> None:
        """All skills are returned (ordered by normalized_text from DB query)."""
        skill_ids = [uuid.uuid4() for _ in range(5)]
        skill_rows = [
            self._make_skill_row(skill_id=sid, normalized_text=f"skill_{i}") for i, sid in enumerate(skill_ids)
        ]
        db = self._make_db(skill_rows=skill_rows, alias_rows=[])

        result = await fetch_all_skills_for_embedding(db)

        assert len(result) == 5
        for record, sid in zip(result, skill_ids, strict=True):
            assert record.id == sid

    @pytest.mark.asyncio
    async def test_executes_exactly_two_queries(self) -> None:
        """Function makes exactly 2 DB calls: one for skills, one for aliases."""
        skill_id = uuid.uuid4()
        skill_row = self._make_skill_row(skill_id=skill_id)
        db = self._make_db(skill_rows=[skill_row], alias_rows=[])

        await fetch_all_skills_for_embedding(db)

        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_table_makes_only_one_query(self) -> None:
        """Short-circuits to one DB call when no skills exist."""
        skill_result = MagicMock()
        skill_result.all.return_value = []
        db = create_mock_session()
        db.execute = AsyncMock(return_value=skill_result)

        await fetch_all_skills_for_embedding(db)

        assert db.execute.call_count == 1


class TestFetchProvenanceForSkillIds:
    """Tests for _fetch_provenance_for_skill_ids helper function."""

    @pytest.mark.asyncio
    async def test_empty_skill_ids_returns_empty_dict(self) -> None:
        """Returns empty dict immediately when skill_ids list is empty."""
        db = create_mock_session()

        result = await _fetch_provenance_for_skill_ids(db, [])

        assert result == {}
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_provenance_keyed_by_skill_id(self) -> None:
        """Returns dict mapping skill_id to provenance record."""
        skill_id = uuid.uuid4()
        mock_prov = MagicMock()
        mock_prov.skill_id = skill_id

        result_mock = MagicMock()
        result_mock.scalars.return_value = [mock_prov]
        db = create_mock_session()
        db.execute = AsyncMock(return_value=result_mock)

        result = await _fetch_provenance_for_skill_ids(db, [skill_id])

        assert skill_id in result
        assert result[skill_id] is mock_prov

    @pytest.mark.asyncio
    async def test_handles_multiple_skill_ids(self) -> None:
        """Returns provenance for multiple skills."""
        skill_id_1 = uuid.uuid4()
        skill_id_2 = uuid.uuid4()
        mock_prov_1 = MagicMock()
        mock_prov_1.skill_id = skill_id_1
        mock_prov_2 = MagicMock()
        mock_prov_2.skill_id = skill_id_2

        result_mock = MagicMock()
        result_mock.scalars.return_value = [mock_prov_1, mock_prov_2]
        db = create_mock_session()
        db.execute = AsyncMock(return_value=result_mock)

        result = await _fetch_provenance_for_skill_ids(db, [skill_id_1, skill_id_2])

        assert len(result) == 2
        assert result[skill_id_1] is mock_prov_1
        assert result[skill_id_2] is mock_prov_2


class TestStreamSkillsWithProvenance:
    """Tests for stream_skills_with_provenance async generator."""

    @pytest.mark.asyncio
    async def test_yields_batches_of_skill_provenance_tuples(self) -> None:
        """Yields batches containing (SkillNode, provenance) tuples."""
        skill_id = uuid.uuid4()
        mock_skill = MagicMock()
        mock_skill.id = skill_id

        mock_prov = MagicMock()
        mock_prov.skill_id = skill_id

        prov_result = MagicMock()
        prov_result.scalars.return_value = [mock_prov]

        db = create_mock_session()
        db.stream_scalars = AsyncMock(return_value=MockAsyncIterator([mock_skill]))
        db.execute = AsyncMock(return_value=prov_result)

        batches = [batch async for batch in stream_skills_with_provenance(db, batch_size=10)]

        assert len(batches) == 1
        assert len(batches[0]) == 1
        skill, prov = batches[0][0]
        assert skill is mock_skill
        assert prov is mock_prov

    @pytest.mark.asyncio
    async def test_empty_table_yields_nothing(self) -> None:
        """No batches yielded when table is empty."""
        db = create_mock_session()
        db.stream_scalars = AsyncMock(return_value=MockAsyncIterator([]))

        batches = [batch async for batch in stream_skills_with_provenance(db)]

        assert batches == []

    @pytest.mark.asyncio
    async def test_respects_batch_size(self) -> None:
        """Yields batches of specified size."""
        skills = [MagicMock(id=uuid.uuid4()) for _ in range(5)]

        prov_result = MagicMock()
        prov_result.scalars.return_value = []

        db = create_mock_session()
        db.stream_scalars = AsyncMock(return_value=MockAsyncIterator(skills))
        db.execute = AsyncMock(return_value=prov_result)

        batches = [batch async for batch in stream_skills_with_provenance(db, batch_size=2)]

        assert len(batches) == 3
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2
        assert len(batches[2]) == 1

    def test_default_batch_size_is_constant(self) -> None:
        """Default batch_size parameter matches SKILL_BATCH_SIZE constant."""
        assert SKILL_BATCH_SIZE == 500

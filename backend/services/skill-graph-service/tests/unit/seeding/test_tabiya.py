"""Tests for TabiyaDataSource CSV parsing."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.strategies import ConflictStrategy, SourceAuthority
from skill_graph_service.seeding.sources.tabiya import (
    TabiyaDataSource,
    _build_occupation_index,
    _build_skill_index,
    _derive_category_map,
    _read_hierarchy_edges,
    _read_skill_groups,
)


@pytest.fixture
def skills_csv(tmp_path: Path) -> Path:
    """Create a temporary skills.csv for testing."""
    csv_path = tmp_path / "skills.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ID",
                "PREFERREDLABEL",
                "ALTLABELS",
                "SKILLTYPE",
                "REUSELEVEL",
                "DESCRIPTION",
                "ORIGINURI",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "ID": "skill-001",
                "PREFERREDLABEL": "Python Programming",
                "ALTLABELS": "Python\nPy coding",
                "SKILLTYPE": "skill/competence",
                "REUSELEVEL": "cross-sector",
                "DESCRIPTION": "Programming in Python",
                "ORIGINURI": "http://example.com/skill/001",
            }
        )
        writer.writerow(
            {
                "ID": "skill-002",
                "PREFERREDLABEL": "JavaScript",
                "ALTLABELS": "",
                "SKILLTYPE": "knowledge",
                "REUSELEVEL": "sector-specific",
                "DESCRIPTION": "",
                "ORIGINURI": "http://example.com/skill/002",
            }
        )
    return csv_path


@pytest.fixture
def occupations_csv(tmp_path: Path) -> Path:
    """Create a temporary occupations.csv for testing."""
    csv_path = tmp_path / "occupations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ID",
                "CODE",
                "PREFERREDLABEL",
                "ALTLABELS",
                "DESCRIPTION",
                "ISCOGROUPCODE",
                "OCCUPATIONTYPE",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "ID": "occ-001",
                "CODE": "2512.1",
                "PREFERREDLABEL": "Software Developer",
                "ALTLABELS": "Programmer\nCoder",
                "DESCRIPTION": "Develops software",
                "ISCOGROUPCODE": "2512",
                "OCCUPATIONTYPE": "escooccupation",
            }
        )
    return csv_path


@pytest.fixture
def skill_relations_csv(tmp_path: Path) -> Path:
    """Create a temporary skill_skill_relations.csv for testing."""
    csv_path = tmp_path / "skill_skill_relations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["REQUIRINGID", "REQUIREDID", "RELATIONTYPE"])
        writer.writeheader()
        writer.writerow(
            {
                "REQUIRINGID": "skill-001",
                "REQUIREDID": "skill-002",
                "RELATIONTYPE": "essential",
            }
        )
    return csv_path


@pytest.fixture
def occupation_skills_csv(tmp_path: Path) -> Path:
    """Create a temporary occupation_skill_relations.csv for testing."""
    csv_path = tmp_path / "occupation_skill_relations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["OCCUPATIONID", "SKILLID", "OCCUPATIONTYPE", "RELATIONTYPE"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "OCCUPATIONID": "occ-001",
                "SKILLID": "skill-001",
                "OCCUPATIONTYPE": "escooccupation",
                "RELATIONTYPE": "essential",
            }
        )
    return csv_path


@pytest.fixture
def skill_groups_csv(tmp_path: Path) -> Path:
    """Create a temporary skillGroups.csv for testing."""
    csv_path = tmp_path / "skillGroups.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ID", "PREFERREDLABEL"])
        writer.writeheader()
        writer.writerow({"ID": "group-001", "PREFERREDLABEL": "Programming"})
        writer.writerow({"ID": "group-002", "PREFERREDLABEL": "Languages"})
    return csv_path


@pytest.fixture
def skills_hierarchy_csv(tmp_path: Path) -> Path:
    """Create a temporary skills_hierarchy.csv for testing."""
    csv_path = tmp_path / "skills_hierarchy.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["CHILDID", "PARENTID", "PARENTOBJECTTYPE"])
        writer.writeheader()
        writer.writerow(
            {
                "CHILDID": "skill-001",
                "PARENTID": "group-001",
                "PARENTOBJECTTYPE": "skillgroup",
            }
        )
        writer.writerow(
            {
                "CHILDID": "group-001",
                "PARENTID": "group-002",
                "PARENTOBJECTTYPE": "skillgroup",
            }
        )
    return csv_path


class TestBuildSkillIndex:
    """Tests for _build_skill_index function."""

    def test_builds_index_from_csv(self, skills_csv: Path) -> None:
        """_build_skill_index creates correct mapping."""
        index = _build_skill_index(skills_csv)
        assert "skill-001" in index
        assert "skill-002" in index
        normalized, uri = index["skill-001"]
        assert normalized == "python programming"
        assert uri == "http://example.com/skill/001"

    def test_skips_empty_id(self, tmp_path: Path) -> None:
        """_build_skill_index skips rows with empty ID."""
        csv_path = tmp_path / "skills.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ID", "PREFERREDLABEL", "ORIGINURI"])
            writer.writeheader()
            writer.writerow({"ID": "", "PREFERREDLABEL": "Test", "ORIGINURI": ""})
        index = _build_skill_index(csv_path)
        assert len(index) == 0

    def test_skips_empty_label(self, tmp_path: Path) -> None:
        """_build_skill_index skips rows with empty label."""
        csv_path = tmp_path / "skills.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["ID", "PREFERREDLABEL", "ORIGINURI"])
            writer.writeheader()
            writer.writerow({"ID": "skill-001", "PREFERREDLABEL": "", "ORIGINURI": ""})
        index = _build_skill_index(csv_path)
        assert len(index) == 0


class TestBuildOccupationIndex:
    """Tests for _build_occupation_index function."""

    def test_builds_index_from_csv(self, occupations_csv: Path) -> None:
        """_build_occupation_index creates correct mapping."""
        index = _build_occupation_index(occupations_csv)
        assert "occ-001" in index
        code, label = index["occ-001"]
        assert code == "2512.1"
        assert label == "Software Developer"


class TestReadSkillGroups:
    """Tests for _read_skill_groups function."""

    def test_reads_groups(self, skill_groups_csv: Path) -> None:
        """_read_skill_groups creates correct mapping."""
        groups = _read_skill_groups(skill_groups_csv)
        assert groups["group-001"] == "Programming"
        assert groups["group-002"] == "Languages"


class TestReadHierarchyEdges:
    """Tests for _read_hierarchy_edges function."""

    def test_reads_edges(self, skills_hierarchy_csv: Path) -> None:
        """_read_hierarchy_edges creates correct mapping."""
        edges = _read_hierarchy_edges(skills_hierarchy_csv)
        assert "skill-001" in edges
        parent_id, parent_type = edges["skill-001"]
        assert parent_id == "group-001"
        assert parent_type == "skillgroup"


class TestDeriveCategoryMap:
    """Tests for _derive_category_map function."""

    def test_single_ancestor(self) -> None:
        """Skill with one skillgroup ancestor gets same category and subcategory."""
        skill_ids = {"skill-001"}
        group_labels = {"group-001": "Programming"}
        child_to_parent = {"skill-001": ("group-001", "skillgroup")}
        result = _derive_category_map(skill_ids, group_labels, child_to_parent)
        assert result["skill-001"] == ("Programming", "Programming")

    def test_no_ancestor(self) -> None:
        """Skill with no skillgroup ancestor gets (None, None)."""
        skill_ids = {"skill-001"}
        group_labels = {}
        child_to_parent: dict[str, tuple[str, str]] = {}
        result = _derive_category_map(skill_ids, group_labels, child_to_parent)
        assert result["skill-001"] == (None, None)

    def test_multiple_ancestors(self) -> None:
        """Skill with multiple ancestors gets category from second-to-last."""
        skill_ids = {"skill-001"}
        group_labels = {"g1": "Sub", "g2": "Parent", "g3": "Root"}
        child_to_parent = {
            "skill-001": ("g1", "skillgroup"),
            "g1": ("g2", "skillgroup"),
            "g2": ("g3", "skillgroup"),
        }
        result = _derive_category_map(skill_ids, group_labels, child_to_parent)
        category, subcategory = result["skill-001"]
        assert subcategory == "Sub"
        assert category == "Parent"


class TestTabiyaDataSourceProperties:
    """Tests for TabiyaDataSource properties."""

    def test_source_name(self, skills_csv: Path) -> None:
        """source_name returns 'tabiya'."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        assert ds.source_name == "tabiya"

    def test_authority(self, skills_csv: Path) -> None:
        """Authority returns SourceAuthority.TABIYA."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        assert ds.authority == SourceAuthority.TABIYA

    def test_conflict_strategy(self, skills_csv: Path) -> None:
        """conflict_strategy returns ConflictStrategy.SKIP."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        assert ds.conflict_strategy == ConflictStrategy.SKIP


class TestTabiyaIterSkills:
    """Tests for TabiyaDataSource.iter_skills."""

    def test_yields_skill_records(self, skills_csv: Path) -> None:
        """iter_skills yields SkillRecord for each valid row."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_skills())
        assert len(records) == 2
        assert all(isinstance(r, SkillRecord) for r in records)

    def test_skill_fields(self, skills_csv: Path) -> None:
        """iter_skills populates SkillRecord fields correctly."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_skills())
        python_record = next(r for r in records if "python" in r.normalized_text)
        assert python_record.normalized_text == "python programming"
        assert python_record.skill_type == "specialized"
        assert python_record.reuse_level == "cross-sector"
        assert python_record.description == "Programming in Python"
        assert python_record.external_id == "skill-001"

    def test_missing_file_fails_closed(self, tmp_path: Path) -> None:
        """A missing required skills CSV aborts seeding instead of reporting success."""
        missing = tmp_path / "nonexistent.csv"
        ds = TabiyaDataSource(skills_csv_path=missing)

        with pytest.raises(FileNotFoundError) as exc_info:
            list(ds.iter_skills())

        assert exc_info.value.filename == str(missing)


class TestTabiyaIterAliases:
    """Tests for TabiyaDataSource.iter_aliases."""

    def test_yields_alias_records(self, skills_csv: Path) -> None:
        """iter_aliases yields AliasRecord for each ALTLABELS entry."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_aliases())
        assert len(records) == 2
        assert all(isinstance(r, AliasRecord) for r in records)

    def test_alias_fields(self, skills_csv: Path) -> None:
        """iter_aliases populates AliasRecord fields correctly."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_aliases())
        python_alias = next(r for r in records if r.alias_text == "python")
        assert python_alias.skill_normalized_text == "python programming"
        assert python_alias.confidence == 0.95


class TestTabiyaIterRelationships:
    """Tests for TabiyaDataSource.iter_relationships."""

    def test_yields_relationship_records(
        self,
        skills_csv: Path,
        skill_relations_csv: Path,
    ) -> None:
        """iter_relationships yields RelationshipRecord for valid rows."""
        ds = TabiyaDataSource(
            skills_csv_path=skills_csv,
            skill_relations_csv_path=skill_relations_csv,
        )
        records = list(ds.iter_relationships())
        assert len(records) == 1
        assert isinstance(records[0], RelationshipRecord)

    def test_skips_when_no_path(self, skills_csv: Path) -> None:
        """iter_relationships yields nothing when path not configured."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_relationships())
        assert records == []

    def test_relationship_fields(
        self,
        skills_csv: Path,
        skill_relations_csv: Path,
    ) -> None:
        """iter_relationships populates RelationshipRecord fields correctly."""
        ds = TabiyaDataSource(
            skills_csv_path=skills_csv,
            skill_relations_csv_path=skill_relations_csv,
        )
        records = list(ds.iter_relationships())
        rel = records[0]
        assert rel.source_normalized_text == "python programming"
        assert rel.target_normalized_text == "javascript"
        assert rel.relationship_type == "essential"
        assert rel.strength == 1.0


class TestTabiyaIterOccupationRelations:
    """Tests for TabiyaDataSource.iter_occupation_relations."""

    def test_yields_occupation_skill_records(
        self,
        skills_csv: Path,
        occupations_csv: Path,
        occupation_skills_csv: Path,
    ) -> None:
        """iter_occupation_relations yields OccupationSkillRecord for valid rows."""
        ds = TabiyaDataSource(
            skills_csv_path=skills_csv,
            occupations_csv_path=occupations_csv,
            occupation_skills_csv_path=occupation_skills_csv,
        )
        records = list(ds.iter_occupation_relations())
        assert len(records) == 1
        assert isinstance(records[0], OccupationSkillRecord)

    def test_skips_when_no_paths(self, skills_csv: Path) -> None:
        """iter_occupation_relations yields nothing when paths not configured."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_occupation_relations())
        assert records == []


class TestTabiyaIterOccupations:
    """Tests for TabiyaDataSource.iter_occupations."""

    def test_yields_occupation_records(
        self,
        skills_csv: Path,
        occupations_csv: Path,
    ) -> None:
        """iter_occupations yields OccupationRecord for valid rows."""
        ds = TabiyaDataSource(
            skills_csv_path=skills_csv,
            occupations_csv_path=occupations_csv,
        )
        records = list(ds.iter_occupations())
        assert len(records) == 1
        assert isinstance(records[0], OccupationRecord)

    def test_skips_when_no_path(self, skills_csv: Path) -> None:
        """iter_occupations yields nothing when path not configured."""
        ds = TabiyaDataSource(skills_csv_path=skills_csv)
        records = list(ds.iter_occupations())
        assert records == []

    def test_occupation_fields(
        self,
        skills_csv: Path,
        occupations_csv: Path,
    ) -> None:
        """iter_occupations populates OccupationRecord fields correctly."""
        ds = TabiyaDataSource(
            skills_csv_path=skills_csv,
            occupations_csv_path=occupations_csv,
        )
        records = list(ds.iter_occupations())
        occ = records[0]
        assert occ.occupation_code == "2512.1"
        assert occ.preferred_label == "Software Developer"
        assert occ.alt_labels == ["Programmer", "Coder"]
        assert occ.isco_group_code == "2512"


class TestTabiyaParseOccupationRecord:
    """Tests for TabiyaDataSource._parse_occupation_record static method."""

    def test_returns_none_for_empty_code(self) -> None:
        """_parse_occupation_record returns None when CODE is empty."""
        row = {"CODE": "", "PREFERREDLABEL": "Test"}
        result = TabiyaDataSource._parse_occupation_record(row)
        assert result is None

    def test_returns_none_for_empty_label(self) -> None:
        """_parse_occupation_record returns None when PREFERREDLABEL is empty."""
        row = {"CODE": "1234", "PREFERREDLABEL": ""}
        result = TabiyaDataSource._parse_occupation_record(row)
        assert result is None

    def test_parses_valid_row(self) -> None:
        """_parse_occupation_record parses valid row correctly."""
        row = {
            "CODE": "2512.1",
            "PREFERREDLABEL": "Software Developer",
            "ALTLABELS": "Programmer\nCoder",
            "DESCRIPTION": "Develops software",
            "ISCOGROUPCODE": "2512",
            "OCCUPATIONTYPE": "escooccupation",
        }
        result = TabiyaDataSource._parse_occupation_record(row)
        assert result is not None
        assert result.occupation_code == "2512.1"
        assert result.preferred_label == "Software Developer"
        assert result.alt_labels == ["Programmer", "Coder"]


class TestTabiyaParseSkillRow:
    """Tests for TabiyaDataSource._parse_skill_row static method."""

    def test_returns_none_for_empty_label(self) -> None:
        """_parse_skill_row returns None when PREFERREDLABEL is empty."""
        row = {"PREFERREDLABEL": "", "ID": "skill-001"}
        result = TabiyaDataSource._parse_skill_row(row, {})
        assert result is None

    def test_parses_valid_row(self) -> None:
        """_parse_skill_row parses valid row correctly."""
        row = {
            "ID": "skill-001",
            "PREFERREDLABEL": "Python Programming",
            "SKILLTYPE": "skill/competence",
            "REUSELEVEL": "cross-sector",
            "DESCRIPTION": "Programming in Python",
            "ORIGINURI": "http://example.com/001",
        }
        category_map = {"skill-001": ("Programming", "Languages")}
        result = TabiyaDataSource._parse_skill_row(row, category_map)
        assert result is not None
        assert result.normalized_text == "python programming"
        assert result.skill_type == "specialized"
        assert result.category == "Programming"
        assert result.subcategory == "Languages"


class TestTabiyaParseAliasRows:
    """Tests for TabiyaDataSource._parse_alias_rows static method."""

    def test_yields_aliases(self) -> None:
        """_parse_alias_rows yields AliasRecord for each valid ALTLABELS entry."""
        row = {"PREFERREDLABEL": "Python", "ALTLABELS": "Py\nPython Lang"}
        records = list(TabiyaDataSource._parse_alias_rows(row))
        assert len(records) == 2

    def test_skips_duplicate_of_canonical(self) -> None:
        """_parse_alias_rows skips aliases that normalize to same as canonical."""
        row = {"PREFERREDLABEL": "Python", "ALTLABELS": "python\nPy"}
        records = list(TabiyaDataSource._parse_alias_rows(row))
        assert len(records) == 1
        assert records[0].alias_text == "py"

    def test_returns_empty_for_no_label(self) -> None:
        """_parse_alias_rows returns empty for missing PREFERREDLABEL."""
        row = {"PREFERREDLABEL": "", "ALTLABELS": "Alias"}
        records = list(TabiyaDataSource._parse_alias_rows(row))
        assert records == []


class TestTabiyaParseRelationshipRow:
    """Tests for TabiyaDataSource._parse_relationship_row static method."""

    def test_returns_none_for_unknown_ids(self) -> None:
        """_parse_relationship_row returns None when IDs not in index."""
        row = {"REQUIRINGID": "unknown", "REQUIREDID": "unknown", "RELATIONTYPE": "essential"}
        result = TabiyaDataSource._parse_relationship_row(row, {})
        assert result is None

    def test_parses_valid_row(self) -> None:
        """_parse_relationship_row parses valid row correctly."""
        row = {"REQUIRINGID": "s1", "REQUIREDID": "s2", "RELATIONTYPE": "essential"}
        skill_index = {"s1": ("python", "uri1"), "s2": ("javascript", "uri2")}
        result = TabiyaDataSource._parse_relationship_row(row, skill_index)
        assert result is not None
        assert result.source_normalized_text == "python"
        assert result.target_normalized_text == "javascript"
        assert result.strength == 1.0

    def test_optional_strength(self) -> None:
        """_parse_relationship_row uses 0.5 strength for non-essential relations."""
        row = {"REQUIRINGID": "s1", "REQUIREDID": "s2", "RELATIONTYPE": "optional"}
        skill_index = {"s1": ("python", "uri1"), "s2": ("javascript", "uri2")}
        result = TabiyaDataSource._parse_relationship_row(row, skill_index)
        assert result is not None
        assert result.strength == 0.5


class TestTabiyaParseOccupationRow:
    """Tests for TabiyaDataSource._parse_occupation_row static method."""

    def test_returns_none_for_unknown_ids(self) -> None:
        """_parse_occupation_row returns None when IDs not in indices."""
        row = {
            "OCCUPATIONID": "unknown",
            "SKILLID": "unknown",
            "OCCUPATIONTYPE": "esco",
            "RELATIONTYPE": "essential",
        }
        result = TabiyaDataSource._parse_occupation_row(row, {}, {})
        assert result is None

    def test_parses_valid_row(self) -> None:
        """_parse_occupation_row parses valid row correctly."""
        row = {
            "OCCUPATIONID": "o1",
            "SKILLID": "s1",
            "OCCUPATIONTYPE": "escooccupation",
            "RELATIONTYPE": "essential",
        }
        skill_index = {"s1": ("python", "uri1")}
        occupation_index = {"o1": ("2512.1", "Developer")}
        result = TabiyaDataSource._parse_occupation_row(row, skill_index, occupation_index)
        assert result is not None
        assert result.occupation_code == "2512.1"
        assert result.occupation_label == "Developer"
        assert result.skill_normalized_text == "python"
        assert result.source_metadata == {"occupation_type": "escooccupation"}

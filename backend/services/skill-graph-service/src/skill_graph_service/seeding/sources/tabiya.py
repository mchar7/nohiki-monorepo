"""TabiyaDataSource: parses Tabiya ESCO (v1.1.1) CSV exports into skill graph records."""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from nohiki_observability import get_logger

from skill_graph_service.seeding.domain.records import (
    AliasRecord,
    OccupationRecord,
    OccupationSkillRecord,
    RelationshipRecord,
    SkillRecord,
)
from skill_graph_service.seeding.domain.strategies import ConflictStrategy, SourceAuthority
from skill_graph_service.seeding.normalizer import normalize_skill_text

logger = get_logger(__name__)

_SOURCE_NAME: Final[str] = "tabiya"
_ALIAS_CONFIDENCE: Final[float] = 0.95
_ESSENTIAL_STRENGTH: Final[float] = 1.0
_OPTIONAL_STRENGTH: Final[float] = 0.5
_DEFAULT_SKILL_TYPE: Final[str] = "specialized"
_SKILLGROUP_OBJECT_TYPE: Final[str] = "skillgroup"

_SKILL_TYPE_MAP: Final[dict[str, str]] = {
    "skill/competence": "specialized",
    "knowledge": "knowledge",
    "language": "language",
    "attitude": "attitude",
}


def _build_skill_index(skills_csv_path: Path) -> dict[str, tuple[str, str]]:
    """Build skill ID to (normalized_label, origin_uri) mapping from skills.csv."""
    index: dict[str, tuple[str, str]] = {}
    with skills_csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            skill_id = row.get("ID", "").strip()
            label = row.get("PREFERREDLABEL", "").strip()
            uri = row.get("ORIGINURI", "").strip()
            if skill_id and (normalized := normalize_skill_text(label)):
                index[skill_id] = (normalized, uri)
    return index


def _build_occupation_index(occupations_csv_path: Path) -> dict[str, tuple[str, str]]:
    """Build occupation ID to (code, label) mapping from occupations.csv."""
    index: dict[str, tuple[str, str]] = {}
    with occupations_csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            occ_id = row.get("ID", "").strip()
            code = row.get("CODE", "").strip()
            label = row.get("PREFERREDLABEL", "").strip()
            if occ_id and label:
                index[occ_id] = (code, label)
    return index


def _read_skill_groups(skill_groups_csv_path: Path) -> dict[str, str]:
    """Read skillGroups.csv into skill group ID to label mapping."""
    groups: dict[str, str] = {}
    with skill_groups_csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            group_id = row.get("ID", "").strip()
            label = row.get("PREFERREDLABEL", "").strip()
            if group_id and label:
                groups[group_id] = label
    return groups


def _read_hierarchy_edges(
    skills_hierarchy_csv_path: Path,
) -> dict[str, tuple[str, str]]:
    """Read skills_hierarchy.csv into child ID to (parent_id, parent_type) mapping."""
    edges: dict[str, tuple[str, str]] = {}
    with skills_hierarchy_csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            child_id = row.get("CHILDID", "").strip()
            parent_id = row.get("PARENTID", "").strip()
            parent_type = row.get("PARENTOBJECTTYPE", "").strip().lower()
            if child_id and parent_id:
                edges[child_id] = (parent_id, parent_type)
    return edges


def _derive_category_map(
    skill_ids: set[str],
    group_labels: dict[str, str],
    child_to_parent: dict[str, tuple[str, str]],
) -> dict[str, tuple[str | None, str | None]]:
    """Derive category and subcategory for each skill by walking up the hierarchy."""
    result: dict[str, tuple[str | None, str | None]] = {}

    for skill_id in skill_ids:
        ancestors: list[str] = []
        visited: set[str] = {skill_id}
        current = skill_id

        while parent_info := child_to_parent.get(current):
            parent_id, parent_type = parent_info
            if parent_id in visited:
                break
            visited.add(parent_id)
            current = parent_id
            if parent_type == _SKILLGROUP_OBJECT_TYPE and parent_id in group_labels:
                ancestors.append(parent_id)

        match ancestors:
            case []:
                result[skill_id] = (None, None)
            case [only]:
                label = group_labels[only]
                result[skill_id] = (label, label)
            case _:
                subcategory = group_labels[ancestors[0]]
                category = group_labels[ancestors[-2]]
                result[skill_id] = (category, subcategory)

    return result


@dataclass(slots=True)
class TabiyaDataSource:
    """Parses Tabiya ESCO v1.1.1 CSV exports and implements the SkillDataSource protocol."""

    skills_csv_path: Path
    skill_relations_csv_path: Path | None = None
    occupation_skills_csv_path: Path | None = None
    occupations_csv_path: Path | None = None
    skill_groups_csv_path: Path | None = None
    skills_hierarchy_csv_path: Path | None = None
    source_version: str = ""
    _skill_index: dict[str, tuple[str, str]] | None = field(init=False, default=None, repr=False, compare=False)
    _occupation_index: dict[str, tuple[str, str]] | None = field(init=False, default=None, repr=False, compare=False)
    _category_map: dict[str, tuple[str | None, str | None]] | None = field(
        init=False, default=None, repr=False, compare=False
    )

    @property
    def source_name(self) -> str:
        """Identifier used in provenance and batch records."""
        return _SOURCE_NAME

    @property
    def authority(self) -> SourceAuthority:
        """Tabiya has standard authority; curated sources outrank it."""
        return SourceAuthority.TABIYA

    @property
    def conflict_strategy(self) -> ConflictStrategy:
        """Skip conflicts so curated corrections are never overwritten."""
        return ConflictStrategy.SKIP

    def iter_skills(self) -> Iterator[SkillRecord]:
        """Stream SkillRecords from skills.csv with hierarchy-derived categories."""
        category_map = self._get_category_map()
        try:
            with self.skills_csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if record := self._parse_skill_row(row, category_map):
                        yield record
        except OSError:
            logger.exception("Cannot open skills CSV", path=str(self.skills_csv_path))
            raise

    def iter_aliases(self) -> Iterator[AliasRecord]:
        """Stream AliasRecords from the ALTLABELS column of skills.csv."""
        try:
            with self.skills_csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    yield from self._parse_alias_rows(row)
        except OSError:
            logger.exception("Cannot open skills CSV for aliases", path=str(self.skills_csv_path))
            raise

    def iter_relationships(self) -> Iterator[RelationshipRecord]:
        """Stream RelationshipRecords from skill_skill_relations.csv."""
        if self.skill_relations_csv_path is None:
            logger.info("No skill relations CSV configured - skipping")
            return
        skill_index = self._get_skill_index()
        try:
            with self.skill_relations_csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if record := self._parse_relationship_row(row, skill_index):
                        yield record
        except OSError:
            logger.exception(
                "Cannot open skill relations CSV",
                path=str(self.skill_relations_csv_path),
            )
            raise

    def iter_occupation_relations(self) -> Iterator[OccupationSkillRecord]:
        """Stream OccupationSkillRecords from occupation_skill_relations.csv."""
        if self.occupation_skills_csv_path is None or self.occupations_csv_path is None:
            logger.info("Occupation skills or occupations CSV not configured - skipping")
            return
        skill_index = self._get_skill_index()
        occupation_index = self._get_occupation_index()
        try:
            with self.occupation_skills_csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if record := self._parse_occupation_row(row, skill_index, occupation_index):
                        yield record
        except OSError:
            logger.exception(
                "Cannot open occupation skills CSV",
                path=str(self.occupation_skills_csv_path),
            )
            raise

    def iter_occupations(self) -> Iterator[OccupationRecord]:
        """Stream OccupationRecords from occupations.csv."""
        if self.occupations_csv_path is None:
            logger.info("Occupations CSV not configured - skipping")
            return
        try:
            with self.occupations_csv_path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if record := self._parse_occupation_record(row):
                        yield record
        except OSError:
            logger.exception(
                "Cannot open occupations CSV",
                path=str(self.occupations_csv_path),
            )
            raise

    @staticmethod
    def _parse_occupation_record(row: dict[str, str]) -> OccupationRecord | None:
        """Parse one occupations.csv row into an OccupationRecord."""
        code = row.get("CODE", "").strip()
        label = row.get("PREFERREDLABEL", "").strip()
        if not code or not label:
            return None
        alt_labels_raw = row.get("ALTLABELS", "").strip()
        alt_labels = [a.strip() for a in alt_labels_raw.split("\n") if a.strip()] if alt_labels_raw else []
        return OccupationRecord(
            occupation_code=code,
            preferred_label=label,
            description=row.get("DESCRIPTION", "").strip() or None,
            alt_labels=alt_labels,
            isco_group_code=row.get("ISCOGROUPCODE", "").strip() or None,
            occupation_type=row.get("OCCUPATIONTYPE", "").strip() or "escooccupation",
        )

    def _get_skill_index(self) -> dict[str, tuple[str, str]]:
        """Return the lazily-built skill ID to (normalized_text, uri) index."""
        if self._skill_index is None:
            try:
                self._skill_index = _build_skill_index(self.skills_csv_path)
            except OSError:
                logger.exception("Cannot build skill index", path=str(self.skills_csv_path))
                raise
        return self._skill_index

    def _get_occupation_index(self) -> dict[str, tuple[str, str]]:
        """Return the lazily-built occupation ID to (code, label) index."""
        if self._occupation_index is None:
            if self.occupations_csv_path is None:
                self._occupation_index = {}
            else:
                try:
                    self._occupation_index = _build_occupation_index(self.occupations_csv_path)
                except OSError:
                    logger.exception(
                        "Cannot build occupation index",
                        path=str(self.occupations_csv_path),
                    )
                    raise
        return self._occupation_index

    def _get_category_map(self) -> dict[str, tuple[str | None, str | None]]:
        """Return the lazily-built skill ID to (category, subcategory) map."""
        if self._category_map is not None:
            return self._category_map
        if self.skill_groups_csv_path is None or self.skills_hierarchy_csv_path is None:
            logger.info("Hierarchy CSVs not configured - categories will be None")
            self._category_map = {}
            return self._category_map
        try:
            skill_ids = set(self._get_skill_index().keys())
            group_labels = _read_skill_groups(self.skill_groups_csv_path)
            child_to_parent = _read_hierarchy_edges(self.skills_hierarchy_csv_path)
            self._category_map = _derive_category_map(skill_ids, group_labels, child_to_parent)
        except OSError:
            logger.exception("Failed to build category map")
            raise
        return self._category_map

    @staticmethod
    def _parse_skill_row(
        row: dict[str, str],
        category_map: Mapping[str, tuple[str | None, str | None]],
    ) -> SkillRecord | None:
        """Parse one skills.csv row into a SkillRecord."""
        preferred_label = row.get("PREFERREDLABEL", "").strip()
        if not preferred_label:
            return None
        normalized = normalize_skill_text(preferred_label)
        if not normalized:
            return None
        skill_id = row.get("ID", "").strip()
        category, subcategory = category_map.get(skill_id, (None, None))
        raw_reuse = row.get("REUSELEVEL", "").strip()
        return SkillRecord(
            normalized_text=normalized,
            display_name=preferred_label if preferred_label.lower() != normalized else None,
            skill_type=_SKILL_TYPE_MAP.get(row.get("SKILLTYPE", "").strip(), _DEFAULT_SKILL_TYPE),
            reuse_level=raw_reuse or None,
            category=category,
            subcategory=subcategory,
            description=row.get("DESCRIPTION", "").strip() or None,
            external_id=skill_id or None,
            external_uri=row.get("ORIGINURI", "").strip() or None,
        )

    @staticmethod
    def _parse_alias_rows(row: dict[str, str]) -> Iterator[AliasRecord]:
        """Yield AliasRecords for each ALTLABELS entry in one skills.csv row."""
        preferred_label = row.get("PREFERREDLABEL", "").strip()
        canonical = normalize_skill_text(preferred_label)
        if not canonical:
            return
        for raw_alias in row.get("ALTLABELS", "").split("\n"):
            alias = raw_alias.strip()
            if not alias:
                continue
            norm_alias = normalize_skill_text(alias)
            if norm_alias and norm_alias != canonical:
                yield AliasRecord(
                    alias_text=norm_alias,
                    skill_normalized_text=canonical,
                    context_hint=None,
                    confidence=_ALIAS_CONFIDENCE,
                )

    @staticmethod
    def _parse_relationship_row(
        row: dict[str, str],
        skill_index: dict[str, tuple[str, str]],
    ) -> RelationshipRecord | None:
        """Parse one skill_skill_relations.csv row into a RelationshipRecord."""
        requiring_id = row.get("REQUIRINGID", "").strip()
        required_id = row.get("REQUIREDID", "").strip()
        relation_type = row.get("RELATIONTYPE", "").strip().lower()
        source_entry = skill_index.get(requiring_id)
        target_entry = skill_index.get(required_id)
        if source_entry is None or target_entry is None:
            logger.debug(
                "Skipping relationship: unresolvable ID(s)",
                requiring_id=requiring_id,
                required_id=required_id,
            )
            return None
        strength = _ESSENTIAL_STRENGTH if relation_type == "essential" else _OPTIONAL_STRENGTH
        return RelationshipRecord(
            source_normalized_text=source_entry[0],
            target_normalized_text=target_entry[0],
            relationship_type=relation_type,
            strength=strength,
            bidirectional=False,
        )

    @staticmethod
    def _parse_occupation_row(
        row: dict[str, str],
        skill_index: dict[str, tuple[str, str]],
        occupation_index: dict[str, tuple[str, str]],
    ) -> OccupationSkillRecord | None:
        """Parse one occupation_skill_relations.csv row into an OccupationSkillRecord."""
        occupation_id = row.get("OCCUPATIONID", "").strip()
        skill_id = row.get("SKILLID", "").strip()
        occupation_type = row.get("OCCUPATIONTYPE", "").strip()
        relation_type = row.get("RELATIONTYPE", "").strip().lower()
        occ_entry = occupation_index.get(occupation_id)
        skill_entry = skill_index.get(skill_id)
        if occ_entry is None or skill_entry is None:
            logger.debug(
                "Skipping occupation relation: unresolvable ID(s)",
                occupation_id=occupation_id,
                skill_id=skill_id,
            )
            return None
        code, label = occ_entry
        return OccupationSkillRecord(
            occupation_code=code,
            occupation_label=label,
            skill_normalized_text=skill_entry[0],
            relation_type=relation_type,
            source_metadata={"occupation_type": occupation_type},
        )

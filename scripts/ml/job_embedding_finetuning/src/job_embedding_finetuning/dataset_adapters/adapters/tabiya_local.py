"""Adapter for local Tabiya ESCO v1.1.1 CSV exports (Tier 0 — Gold).

Generates training pairs from the complete ESCO taxonomy stored in data/tabiya/.
Reimplements normalize_skill_text() locally (cannot import from skill-graph-service).

Pair types generated:
    - occupation_skill: occupation label → skill label (64,891 essential + 58,897 optional)
    - skill_synonym: preferred label ↔ alt label (~97,483 from skills.csv ALTLABELS)
    - occupation_synonym: preferred label ↔ alt label (~32,804 from occupations.csv ALTLABELS)
    - skill_description: skill name → description (~13,896)
    - occupation_description: occupation name → description (~3,007)
    - skill_relationship: requiring skill → required skill (5,897)
"""

from __future__ import annotations

import csv
import logging
from typing import TYPE_CHECKING, ClassVar

from job_embedding_finetuning.config.defaults import TABIYA_DATA_DIR
from job_embedding_finetuning.dataset_adapters.base import (
    DatasetAdapter,
    DatasetInfo,
    DatasetTier,
    TrainingPair,
)
from job_embedding_finetuning.dataset_adapters.registry import register_adapter
from job_embedding_finetuning.processing.normalizer import normalize_skill_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

logger = logging.getLogger(__name__)


class TabiyaLocalAdapter(DatasetAdapter):
    """Adapter for local Tabiya ESCO v1.1.1 CSV exports.

    Reads CSVs directly via csv.DictReader, joins IDs to text, and generates
    pairs with pair_type tags for instruction prefix mapping.

    The adapter does NOT generate alt-name cross-products. Only preferred_label ↔
    alt_label pairs are generated, not C(n,2) pairs among alt_labels. Cross-products
    produce trivially similar text that inflates the dataset without adding signal.
    """

    DATASET_INFO: ClassVar[DatasetInfo] = DatasetInfo(
        name="tabiya-esco-local",
        hf_repo="local",
        tier=DatasetTier.GOLD,
        description="Complete ESCO v1.1.1 taxonomy from data/tabiya/ (172K records)",
        estimated_rows=172111,
        local_dir_name="tabiya",
    )

    def __init__(self, data_dir: Path) -> None:
        """Initialize the adapter."""
        super().__init__(data_dir)
        self._skill_index: dict[str, tuple[str, str, list[str]]] = {}
        self._occ_index: dict[str, tuple[str, str, str, list[str], str]] = {}

    @property
    def local_path(self) -> Path:
        """Override: read from repo-root data/tabiya/, not settings.data_dir."""
        return TABIYA_DATA_DIR

    def is_downloaded(self) -> bool:
        """Override: check repo-root path, not download directory."""
        return self.local_path.exists() and (self.local_path / "skills.csv").exists()

    def load(self) -> None:
        """Load indices from Tabiya CSV files."""
        self._skill_index = self._build_skill_index()
        self._occ_index = self._build_occupation_index()
        total = len(self._skill_index) + len(self._occ_index)
        self._stats.total_rows = total
        self._stats.valid_rows = total
        self._is_loaded = True
        logger.info(
            "Tabiya loaded: %d skills, %d occupations",
            len(self._skill_index),
            len(self._occ_index),
        )

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate all pair types from Tabiya ESCO data."""
        if not self._is_loaded:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        counts: dict[str, int] = {}
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for pair in self._generate_all():
            pair_type = pair.pair_type
            counts[pair_type] = counts.get(pair_type, 0) + 1
            unique_anchors.add(pair.anchor)
            unique_positives.add(pair.positive)
            yield pair

        total = sum(counts.values())
        self._stats.pairs_generated = total
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types = counts

    def _generate_all(self) -> Iterator[TrainingPair]:
        """Chain all pair generators."""
        yield from self._generate_occupation_skill_pairs()
        yield from self._generate_skill_synonym_pairs()
        yield from self._generate_occupation_synonym_pairs()
        yield from self._generate_skill_description_pairs()
        yield from self._generate_occupation_description_pairs()
        yield from self._generate_skill_relationship_pairs()

    # ═══════════════════════════════════════════════════════════════════════════
    # Index builders
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_skill_index(self) -> dict[str, tuple[str, str, list[str]]]:
        """Build skill index: {ID: (normalized_label, description, alt_labels)}.

        Mirrors skill-graph-service tabiya.py _build_skill_index() logic.
        """
        index: dict[str, tuple[str, str, list[str]]] = {}
        path = self.local_path / "skills.csv"

        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                skill_id = row.get("ID", "").strip()
                preferred = row.get("PREFERREDLABEL", "").strip()
                description = row.get("DESCRIPTION", "").strip()
                alt_raw = row.get("ALTLABELS", "").strip()

                if not skill_id or not preferred:
                    continue

                normalized = normalize_skill_text(preferred)
                alt_labels = _parse_alt_labels(alt_raw)
                index[skill_id] = (normalized, description, alt_labels)

        logger.debug("Built skill index: %d entries", len(index))
        return index

    def _build_occupation_index(self) -> dict[str, tuple[str, str, str, list[str], str]]:
        """Build occupation index: {ID: (code, label, description, alt_labels, isco_code)}.

        Mirrors skill-graph-service tabiya.py _build_occupation_index() logic.
        """
        index: dict[str, tuple[str, str, str, list[str], str]] = {}
        path = self.local_path / "occupations.csv"

        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                occ_id = row.get("ID", "").strip()
                code = row.get("CODE", "").strip()
                label = row.get("PREFERREDLABEL", "").strip()
                description = row.get("DESCRIPTION", "").strip()
                alt_raw = row.get("ALTLABELS", "").strip()
                isco_code = row.get("ISCOGROUPCODE", "").strip()

                if not occ_id or not label:
                    continue

                alt_labels = _parse_alt_labels(alt_raw)
                index[occ_id] = (code, label, description, alt_labels, isco_code)

        logger.debug("Built occupation index: %d entries", len(index))
        return index

    # ═══════════════════════════════════════════════════════════════════════════
    # Pair generators
    # ═══════════════════════════════════════════════════════════════════════════

    def _generate_occupation_skill_pairs(self) -> Iterator[TrainingPair]:
        """Generate occupation→skill pairs from occupation_skill_relations.csv.

        Essential pairs get label=1.0, optional pairs get label=0.5.
        Skip rows where either occupation or skill ID is not found in the index.
        """
        path = self.local_path / "occupation_skill_relations.csv"
        if not path.exists():
            return

        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                occ_id = row.get("OCCUPATIONID", "").strip()
                skill_id = row.get("SKILLID", "").strip()
                relation_type = row.get("RELATIONTYPE", "").strip().lower()

                occ_entry = self._occ_index.get(occ_id)
                skill_entry = self._skill_index.get(skill_id)
                if occ_entry is None or skill_entry is None:
                    continue

                _code, occ_label, _desc, _alts, _isco = occ_entry
                skill_label, _skill_desc, _skill_alts = skill_entry

                if not occ_label or not skill_label:
                    continue

                label = 1.0 if relation_type == "essential" else 0.5

                yield TrainingPair(
                    anchor=normalize_skill_text(occ_label),
                    positive=skill_label,
                    source_dataset=self.info.name,
                    pair_type="occupation_skill",
                    label=label,
                )

    def _generate_skill_synonym_pairs(self) -> Iterator[TrainingPair]:
        """Generate preferred_label ↔ alt_label pairs from skills.csv ALTLABELS."""
        for normalized_label, _desc, alt_labels in self._skill_index.values():
            for alt in alt_labels:
                normalized_alt = normalize_skill_text(alt)
                if normalized_alt and normalized_alt != normalized_label:
                    yield TrainingPair(
                        anchor=normalized_label,
                        positive=normalized_alt,
                        source_dataset=self.info.name,
                        pair_type="skill_synonym",
                    )

    def _generate_occupation_synonym_pairs(self) -> Iterator[TrainingPair]:
        """Generate preferred_label ↔ alt_label pairs from occupations.csv ALTLABELS."""
        for _code, label, _desc, alt_labels, _isco in self._occ_index.values():
            normalized_label = normalize_skill_text(label)
            for alt in alt_labels:
                normalized_alt = normalize_skill_text(alt)
                if normalized_alt and normalized_alt != normalized_label:
                    yield TrainingPair(
                        anchor=normalized_label,
                        positive=normalized_alt,
                        source_dataset=self.info.name,
                        pair_type="occupation_synonym",
                    )

    def _generate_skill_description_pairs(self) -> Iterator[TrainingPair]:
        """Generate skill name → description pairs."""
        for normalized_label, description, _alts in self._skill_index.values():
            if normalized_label and description:
                yield TrainingPair(
                    anchor=normalized_label,
                    positive=description[:512],
                    source_dataset=self.info.name,
                    pair_type="skill_description",
                )

    def _generate_occupation_description_pairs(self) -> Iterator[TrainingPair]:
        """Generate occupation name → description pairs."""
        for _code, label, description, _alts, _isco in self._occ_index.values():
            normalized_label = normalize_skill_text(label)
            if normalized_label and description:
                yield TrainingPair(
                    anchor=normalized_label,
                    positive=description[:512],
                    source_dataset=self.info.name,
                    pair_type="occupation_description",
                )

    def _generate_skill_relationship_pairs(self) -> Iterator[TrainingPair]:
        """Generate requiring→required pairs from skill_skill_relations.csv (both directions)."""
        path = self.local_path / "skill_skill_relations.csv"
        if not path.exists():
            return

        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                requiring_id = row.get("REQUIRINGID", "").strip()
                required_id = row.get("REQUIREDID", "").strip()

                requiring_entry = self._skill_index.get(requiring_id)
                required_entry = self._skill_index.get(required_id)
                if requiring_entry is None or required_entry is None:
                    continue

                requiring_label = requiring_entry[0]
                required_label = required_entry[0]

                if not requiring_label or not required_label:
                    continue

                # Both directions for symmetric learning
                yield TrainingPair(
                    anchor=requiring_label,
                    positive=required_label,
                    source_dataset=self.info.name,
                    pair_type="skill_relationship",
                )
                yield TrainingPair(
                    anchor=required_label,
                    positive=requiring_label,
                    source_dataset=self.info.name,
                    pair_type="skill_relationship",
                )


def _parse_alt_labels(raw: str) -> list[str]:
    """Parse ALTLABELS field — newline-separated list within quoted CSV field.

    The field value contains literal newline characters separating alt labels.
    Empty entries and whitespace-only entries are filtered out.
    """
    if not raw:
        return []
    return [label.strip() for label in raw.split("\n") if label.strip()]


register_adapter(TabiyaLocalAdapter.DATASET_INFO, TabiyaLocalAdapter)

"""Data loading and pair generation for threshold calibration.

Loads Tabiya/ESCO skills and generates test pairs for calibration:
- TRUE_SYNONYM: preferred label vs alternative labels (should auto-match)
- DISTINCT_SIMILAR: different skills sharing words (must NOT auto-match)
- SYNTHETIC_SYNONYM: generated pairs that SHOULD match but aren't in aliases

NOTE: Tabiya data quality varies. High-similarity "distinct" pairs should be
manually reviewed to verify they are genuinely distinct.
"""

from __future__ import annotations

import csv
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

MIN_WORD_LENGTH = 3
MIN_SKILLS_FOR_PAIR = 2


class PairType(Enum):
    """Type of test pair for calibration."""

    TRUE_SYNONYM = "true_synonym"
    DISTINCT_SIMILAR = "distinct_similar"


@dataclass(frozen=True, slots=True)
class SkillEntry:
    """A skill from the Tabiya/ESCO taxonomy."""

    key_id: str
    preferred_label: str
    alternative_labels: tuple[str, ...]
    skill_type: str
    description: str


@dataclass(frozen=True, slots=True)
class TestPair:
    """A pair of skill texts for similarity testing."""

    skill_a: str
    skill_b: str
    pair_type: PairType
    source_skill_id: str
    target_skill_id: str | None


@dataclass
class CalibrationDataset:
    """Container for calibration test pairs."""

    true_synonyms: list[TestPair] = field(default_factory=list)
    distinct_similar: list[TestPair] = field(default_factory=list)

    @property
    def total_pairs(self) -> int:
        """Total number of test pairs."""
        return len(self.true_synonyms) + len(self.distinct_similar)

    @property
    def synonym_count(self) -> int:
        """Number of true synonym pairs."""
        return len(self.true_synonyms)

    @property
    def distinct_count(self) -> int:
        """Number of distinct-but-similar pairs."""
        return len(self.distinct_similar)


class TabiyaLoader:
    """Loads skills from Tabiya/ESCO CSV format."""

    STOP_WORDS: frozenset[str] = frozenset(
        {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "are",
            "was",
            "were",
            "been",
            "being",
            "have",
            "has",
            "had",
            "does",
            "did",
            "doing",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "use",
            "using",
            "used",
            "make",
            "made",
            "such",
            "into",
            "than",
            "then",
            "other",
            "which",
            "their",
            "there",
            "these",
            "those",
            "some",
            "any",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "only",
            "own",
            "same",
            "very",
            "just",
            "also",
            "well",
            "how",
            "when",
            "where",
            "what",
            "who",
            "whom",
            "why",
            "apply",
            "ensure",
            "maintain",
            "manage",
            "perform",
            "provide",
            "support",
            "develop",
            "implement",
            "work",
            "working",
            "works",
            "able",
            "ability",
            "skills",
            "skill",
        },
    )

    def __init__(self, csv_path: Path) -> None:
        """Initialize loader with path to skills CSV."""
        self.csv_path = csv_path
        self._skills: list[SkillEntry] | None = None

    def load(self) -> list[SkillEntry]:
        """Load skills from CSV file."""
        if self._skills is not None:
            return self._skills

        skills: list[SkillEntry] = []
        with self.csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_columns = {"ID", "PREFERREDLABEL"}
            missing_columns = required_columns.difference(reader.fieldnames or ())
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                msg = f"Skills CSV is missing required columns: {missing}"
                raise ValueError(msg)
            for row in reader:
                skill = self._parse_row(row)
                if skill:
                    skills.append(skill)

        self._skills = skills
        return skills

    def _parse_row(self, row: dict[str, str]) -> SkillEntry | None:
        """Parse a CSV row into a SkillEntry."""
        key_id = (row.get("ID") or "").strip()
        if not key_id:
            return None

        preferred_label = (row.get("PREFERREDLABEL") or "").strip()
        if not preferred_label:
            return None

        alt_labels_raw = row.get("ALTLABELS") or ""
        alt_labels = self._parse_alt_labels(alt_labels_raw, preferred_label)

        return SkillEntry(
            key_id=key_id,
            preferred_label=preferred_label,
            alternative_labels=alt_labels,
            skill_type=(row.get("SKILLTYPE") or "skill").strip(),
            description=(row.get("DESCRIPTION") or "").strip(),
        )

    def _parse_alt_labels(self, raw: str, preferred: str) -> tuple[str, ...]:
        """Parse alternative labels, excluding the preferred label."""
        labels = [
            label.strip() for label in raw.split("\n") if label.strip() and label.strip().lower() != preferred.lower()
        ]
        return tuple(labels)

    @property
    def skill_count(self) -> int:
        """Number of loaded skills."""
        return len(self.load())


class PairGenerator:
    """Generates test pairs from loaded skills."""

    def __init__(self, skills: list[SkillEntry], seed: int = 42) -> None:
        """Initialize generator with skills and random seed."""
        self.skills = skills
        self.seed = seed
        self._rng = random.Random(seed)

    def generate_synonym_pairs(self, max_pairs: int | None = None) -> list[TestPair]:
        """Generate TRUE_SYNONYM pairs from preferred labels and alternatives."""
        if max_pairs is not None and max_pairs < 1:
            msg = "max_pairs must be at least 1"
            raise ValueError(msg)
        pairs: list[TestPair] = [
            TestPair(
                skill_a=skill.preferred_label,
                skill_b=alt_label,
                pair_type=PairType.TRUE_SYNONYM,
                source_skill_id=skill.key_id,
                target_skill_id=skill.key_id,
            )
            for skill in sorted(self.skills, key=lambda item: (item.key_id, item.preferred_label.casefold()))
            for alt_label in sorted(skill.alternative_labels, key=str.casefold)
            if alt_label.lower() != skill.preferred_label.lower()
        ]

        if max_pairs and len(pairs) > max_pairs:
            self._rng.shuffle(pairs)
            pairs = pairs[:max_pairs]

        return sorted(pairs, key=_pair_order_key)

    def generate_distinct_pairs(self, max_pairs: int = 50000) -> list[TestPair]:
        """Generate a bounded sample of pairs for different skills sharing words."""
        if max_pairs < 1:
            msg = "max_pairs must be at least 1"
            raise ValueError(msg)
        word_to_skills = self._build_word_index()
        pairs = self._generate_pairs_from_index(word_to_skills, limit=max_pairs * 2)

        self._rng.shuffle(pairs)
        return sorted(pairs[:max_pairs], key=_pair_order_key)

    def generate_substring_pairs(self, max_pairs: int = 10000) -> list[TestPair]:
        """Generate a bounded sample where one skill name is a substring of another."""
        if max_pairs < 1:
            msg = "max_pairs must be at least 1"
            raise ValueError(msg)
        sorted_by_len = sorted(
            self.skills,
            key=lambda skill: (len(skill.preferred_label), skill.key_id, skill.preferred_label.casefold()),
        )
        pairs = self._collect_substring_pairs(sorted_by_len, max_pairs * 2)
        self._rng.shuffle(pairs)
        return sorted(pairs[:max_pairs], key=_pair_order_key)

    def _collect_substring_pairs(
        self,
        sorted_skills: list[SkillEntry],
        limit: int,
    ) -> list[TestPair]:
        """Collect substring pairs up to limit from length-sorted skills."""
        pairs: list[TestPair] = []
        seen: set[tuple[str, str]] = set()

        for i, shorter in enumerate(sorted_skills):
            if len(pairs) >= limit:
                break
            matches = self._find_longer_matches(shorter, sorted_skills[i + 1 :], seen, limit - len(pairs))
            pairs.extend(matches)

        return pairs

    def _find_longer_matches(
        self,
        shorter: SkillEntry,
        candidates: list[SkillEntry],
        seen: set[tuple[str, str]],
        remaining: int,
    ) -> list[TestPair]:
        """Find pairs where shorter skill label is a substring of a longer candidate label."""
        matches: list[TestPair] = []
        shorter_lower = shorter.preferred_label.lower()

        for longer in candidates:
            if len(matches) >= remaining:
                break
            if shorter.key_id == longer.key_id:
                continue
            if shorter_lower not in longer.preferred_label.lower():
                continue
            pair_key: tuple[str, str] = (min(shorter.key_id, longer.key_id), max(shorter.key_id, longer.key_id))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            matches.append(
                TestPair(
                    skill_a=shorter.preferred_label,
                    skill_b=longer.preferred_label,
                    pair_type=PairType.DISTINCT_SIMILAR,
                    source_skill_id=shorter.key_id,
                    target_skill_id=longer.key_id,
                ),
            )

        return matches

    def _build_word_index(self) -> dict[str, list[SkillEntry]]:
        """Build index of significant words to skills."""
        word_to_skills: dict[str, list[SkillEntry]] = defaultdict(list)

        for skill in sorted(self.skills, key=lambda item: (item.key_id, item.preferred_label.casefold())):
            words = sorted(self._extract_significant_words(skill.preferred_label))
            for word in words:
                word_to_skills[word].append(skill)

        return word_to_skills

    def _generate_pairs_from_index(
        self,
        word_to_skills: dict[str, list[SkillEntry]],
        limit: int,
    ) -> list[TestPair]:
        """Generate distinct pairs from the word index without unbounded accumulation."""
        pairs: list[TestPair] = []
        seen: set[tuple[str, str]] = set()

        for word in sorted(word_to_skills):
            skill_list = sorted(word_to_skills[word], key=lambda item: (item.key_id, item.preferred_label.casefold()))
            if len(skill_list) < MIN_SKILLS_FOR_PAIR:
                continue

            for i, skill_a in enumerate(skill_list):
                for skill_b in skill_list[i + 1 :]:
                    pair = self._create_distinct_pair(skill_a, skill_b, seen)
                    if pair:
                        pairs.append(pair)
                        if len(pairs) >= limit:
                            return pairs

        return pairs

    def _create_distinct_pair(
        self,
        skill_a: SkillEntry,
        skill_b: SkillEntry,
        seen: set[tuple[str, str]],
    ) -> TestPair | None:
        """Create a distinct pair if valid and not seen."""
        if skill_a.key_id == skill_b.key_id:
            return None

        pair_key: tuple[str, str] = (min(skill_a.key_id, skill_b.key_id), max(skill_a.key_id, skill_b.key_id))
        if pair_key in seen:
            return None
        seen.add(pair_key)

        if skill_a.preferred_label.lower() == skill_b.preferred_label.lower():
            return None

        return TestPair(
            skill_a=skill_a.preferred_label,
            skill_b=skill_b.preferred_label,
            pair_type=PairType.DISTINCT_SIMILAR,
            source_skill_id=skill_a.key_id,
            target_skill_id=skill_b.key_id,
        )

    def _extract_significant_words(self, text: str) -> set[str]:
        """Extract significant words excluding stop words."""
        words = set(re.findall(r"[a-z]+", text.lower()))
        return {w for w in words if len(w) >= MIN_WORD_LENGTH and w not in TabiyaLoader.STOP_WORDS}


def generate_calibration_dataset(
    csv_path: Path,
    max_synonym_pairs: int = 100000,
    max_distinct_pairs: int = 50000,
    max_substring_pairs: int = 10000,
    seed: int = 42,
) -> CalibrationDataset:
    """Generate a complete calibration dataset from Tabiya CSV."""
    loader = TabiyaLoader(csv_path)
    skills = loader.load()

    generator = PairGenerator(skills, seed=seed)

    synonyms = generator.generate_synonym_pairs(max_pairs=max_synonym_pairs)
    distinct = generator.generate_distinct_pairs(max_pairs=max_distinct_pairs)
    substring = generator.generate_substring_pairs(max_pairs=min(max_substring_pairs, max_distinct_pairs))

    # Keep substring-derived negatives ahead of overlapping generic pairs so the bounded sample retains them.
    all_distinct = _deduplicate_pairs(substring + distinct)[:max_distinct_pairs]

    return CalibrationDataset(
        true_synonyms=synonyms,
        distinct_similar=all_distinct,
    )


def _pair_identity(pair: TestPair) -> tuple[str, str]:
    """Return the order-independent identity used for distinct pairs."""
    target = pair.target_skill_id or ""
    return min(pair.source_skill_id, target), max(pair.source_skill_id, target)


def _is_substring_pair(pair: TestPair) -> bool:
    """Identify pairs generated from a preferred-label substring relationship."""
    return (
        pair.pair_type is PairType.DISTINCT_SIMILAR
        and pair.skill_a.casefold() != pair.skill_b.casefold()
        and pair.skill_a.casefold() in pair.skill_b.casefold()
    )


def _pair_order_key(pair: TestPair) -> tuple[int, str, str, str, str, str]:
    """Return a deterministic order that prioritizes substring-derived pairs."""
    source_id, target_id = _pair_identity(pair)
    return (
        0 if _is_substring_pair(pair) else 1,
        source_id,
        target_id,
        pair.skill_a.casefold(),
        pair.skill_b.casefold(),
        pair.pair_type.value,
    )


def _deduplicate_pairs(pairs: list[TestPair]) -> list[TestPair]:
    """Remove duplicate pairs based on skill IDs with deterministic ordering."""
    unique: dict[tuple[str, str], TestPair] = {}
    for pair in pairs:
        key = _pair_identity(pair)
        if (existing := unique.get(key)) is None or _pair_order_key(pair) < _pair_order_key(existing):
            unique[key] = pair

    return sorted(unique.values(), key=_pair_order_key)

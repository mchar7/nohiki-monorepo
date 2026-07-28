"""Adapters for job description datasets (Tier 2 - Supplementary)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from job_embedding_finetuning.dataset_adapters.base import (
    DatasetAdapter,
    DatasetInfo,
    DatasetTier,
    TrainingPair,
)
from job_embedding_finetuning.dataset_adapters.registry import register_adapter

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_DESCRIPTION_LENGTH = 512
TITLE_COLUMN_NAMES = ("Job_Title", "Job Title", "job_title", "title", "Title")
SKILLS_COLUMN_NAMES = ("skills", "Skills")
DESCRIPTION_COLUMN_NAMES = ("Job_Description", "Job Description", "job_description", "description")
ROLE_COLUMN_NAMES = ("Role", "role")


def _find_data_file(directory: Path) -> Path | None:
    """Find first parquet or CSV file in directory."""
    for pattern in ("*.parquet", "*.csv"):
        matches = list(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def _load_data_file(path: Path) -> pd.DataFrame:
    """Load DataFrame from parquet or CSV, normalizing column names."""
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    # Normalize column names: replace spaces with underscores for itertuples compatibility
    df.columns = [col.replace(" ", "_") for col in df.columns]
    return df


def _get_column_value(row: object, candidates: tuple[str, ...]) -> str:
    """Get first non-empty value from candidate column names (works with namedtuples)."""
    for col in candidates:
        val = getattr(row, col, None) if hasattr(row, col) else None
        if val is not None and str(val).strip() and str(val) != "nan":
            return str(val).strip()
    return ""


def _parse_comma_separated(text: str) -> list[str]:
    """Split comma-separated string into non-empty parts."""
    if not text:
        return []
    return [s.strip() for s in text.split(",") if s.strip()]


class JobDescriptionCleanedAdapter(DatasetAdapter):
    """Adapter for ardavey/job-description-cleaned dataset.

    Contains cleaned job descriptions with structured skills.
    """

    DATASET_INFO = DatasetInfo(
        name="job-description-cleaned",
        hf_repo="ardavey/job-description-cleaned",
        tier=DatasetTier.SUPPLEMENTARY,
        description="Cleaned job descriptions with structured skills",
        estimated_rows=50000,
        local_dir_name="job_description_cleaned",
    )

    def __init__(self, data_dir: Path) -> None:
        """Initialize the adapter."""
        super().__init__(data_dir)
        self._data: pd.DataFrame | None = None

    @property
    def info(self) -> DatasetInfo:
        """Return dataset metadata."""
        return self.DATASET_INFO

    def load(self) -> None:
        """Load the dataset from local storage."""
        data_file = _find_data_file(self.local_path)
        if data_file is None:
            msg = f"No data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = _load_data_file(data_file)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data)
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate training pairs from job descriptions."""
        if not self._is_loaded or self._data is None:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        title_skill_count = 0
        title_desc_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            job_title = _get_column_value(row, TITLE_COLUMN_NAMES)
            skills_str = _get_column_value(row, SKILLS_COLUMN_NAMES)
            description = _get_column_value(row, DESCRIPTION_COLUMN_NAMES)

            for pair in self._make_skill_pairs(job_title, skills_str, unique_anchors, unique_positives):
                title_skill_count += 1
                yield pair

            desc_pair = self._make_description_pair(job_title, description, unique_anchors, unique_positives)
            if desc_pair:
                title_desc_count += 1
                yield desc_pair

        self._stats.pairs_generated = title_skill_count + title_desc_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["title_skill"] = title_skill_count
        self._stats.pair_types["title_description"] = title_desc_count

    def _make_skill_pairs(
        self,
        job_title: str,
        skills_str: str,
        anchors: set[str],
        positives: set[str],
    ) -> Iterator[TrainingPair]:
        """Generate title-skill training pairs."""
        if not job_title or not skills_str:
            return
        anchors.add(job_title)
        for skill in _parse_comma_separated(skills_str):
            positives.add(skill)
            yield TrainingPair(anchor=job_title, positive=skill, source_dataset=self.info.name, pair_type="title_skill")

    def _make_description_pair(
        self,
        job_title: str,
        description: str,
        anchors: set[str],
        positives: set[str],
    ) -> TrainingPair | None:
        """Create a title-description training pair."""
        if not job_title or not description:
            return None
        truncated = description[:MAX_DESCRIPTION_LENGTH]
        anchors.add(job_title)
        positives.add(truncated)
        return TrainingPair(
            anchor=job_title, positive=truncated, source_dataset=self.info.name, pair_type="title_description"
        )


class Lof223JobDescriptionAdapter(DatasetAdapter):
    """Adapter for lof223/job_description dataset.

    Contains job descriptions with skills and responsibilities.
    """

    DATASET_INFO = DatasetInfo(
        name="lof223-job-description",
        hf_repo="lof223/job_description",
        tier=DatasetTier.SUPPLEMENTARY,
        description="Job descriptions with skills and responsibilities",
        estimated_rows=100000,
        license="Apache-2.0",
        local_dir_name="lof223_job_description",
    )

    def __init__(self, data_dir: Path) -> None:
        """Initialize the adapter."""
        super().__init__(data_dir)
        self._data: pd.DataFrame | None = None

    @property
    def info(self) -> DatasetInfo:
        """Return dataset metadata."""
        return self.DATASET_INFO

    def load(self) -> None:
        """Load the dataset from local storage."""
        data_file = _find_data_file(self.local_path)
        if data_file is None:
            msg = f"No data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = _load_data_file(data_file)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data)
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate training pairs from job descriptions."""
        if not self._is_loaded or self._data is None:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        title_skill_count = 0
        role_title_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            job_title = _get_column_value(row, TITLE_COLUMN_NAMES)
            skills_str = _get_column_value(row, SKILLS_COLUMN_NAMES)
            role = _get_column_value(row, ROLE_COLUMN_NAMES)

            for pair in self._make_skill_pairs(job_title, skills_str, unique_anchors, unique_positives):
                title_skill_count += 1
                yield pair

            role_pair = self._make_role_pair(role, job_title, unique_anchors, unique_positives)
            if role_pair:
                role_title_count += 1
                yield role_pair

        self._stats.pairs_generated = title_skill_count + role_title_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["title_skill"] = title_skill_count
        self._stats.pair_types["role_title"] = role_title_count

    def _make_skill_pairs(
        self,
        job_title: str,
        skills_str: str,
        anchors: set[str],
        positives: set[str],
    ) -> Iterator[TrainingPair]:
        """Generate title-skill training pairs."""
        if not job_title or not skills_str:
            return
        anchors.add(job_title)
        for skill in _parse_comma_separated(skills_str):
            positives.add(skill)
            yield TrainingPair(anchor=job_title, positive=skill, source_dataset=self.info.name, pair_type="title_skill")

    def _make_role_pair(
        self,
        role: str,
        job_title: str,
        anchors: set[str],
        positives: set[str],
    ) -> TrainingPair | None:
        """Create a role-title normalization pair."""
        if not role or not job_title or role == job_title:
            return None
        anchors.add(role)
        positives.add(job_title)
        return TrainingPair(anchor=role, positive=job_title, source_dataset=self.info.name, pair_type="role_title")


register_adapter(JobDescriptionCleanedAdapter.DATASET_INFO, JobDescriptionCleanedAdapter)
register_adapter(Lof223JobDescriptionAdapter.DATASET_INFO, Lof223JobDescriptionAdapter)

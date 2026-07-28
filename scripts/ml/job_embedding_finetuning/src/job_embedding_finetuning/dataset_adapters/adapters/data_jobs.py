"""Adapter for lukebarousse/data_jobs dataset (Tier 1 - Core)."""

from __future__ import annotations

import ast
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


def _parse_skills_list(skills_str: str) -> list[str]:
    """Parse skills from string representation like "['python', 'sql']"."""
    if not skills_str or pd.isna(skills_str):
        return []

    try:
        parsed = ast.literal_eval(skills_str)
        if isinstance(parsed, list):
            return [str(s).strip() for s in parsed if s]
    except ValueError, SyntaxError:
        pass

    if skills_str.startswith("[") and skills_str.endswith("]"):
        inner = skills_str[1:-1]
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]

    return []


class DataJobsAdapter(DatasetAdapter):
    """Adapter for lukebarousse/data_jobs dataset.

    Contains 786K job postings with extracted skills.
    """

    DATASET_INFO = DatasetInfo(
        name="data-jobs",
        hf_repo="lukebarousse/data_jobs",
        tier=DatasetTier.CORE,
        description="786K job postings with extracted skills",
        estimated_rows=786000,
        license="Apache-2.0",
        local_dir_name="data_jobs",
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
        csv_path = self.local_path / "data_jobs.csv"
        if not csv_path.exists():
            msg = f"Dataset not found: {csv_path}"
            raise FileNotFoundError(msg)

        self._data = pd.read_csv(csv_path)
        self._stats.total_rows = len(self._data)

        # Vectorized check for valid rows (has skills)
        skills_col = self._data.get("job_skills", pd.Series())
        self._stats.valid_rows = int((skills_col.notna() & (skills_col != "")).sum())
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate training pairs from job postings."""
        if not self._is_loaded or self._data is None:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        title_skill_count = 0
        title_norm_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            job_title = str(getattr(row, "job_title", "") or "").strip()
            job_title_short = str(getattr(row, "job_title_short", "") or "").strip()
            skills_str = str(getattr(row, "job_skills", "") or "")
            skills = _parse_skills_list(skills_str)

            for pair in self._generate_title_skill_pairs(job_title, skills, unique_anchors, unique_positives):
                title_skill_count += 1
                yield pair

            norm_pair = self._generate_title_normalization_pair(job_title, job_title_short)
            if norm_pair:
                title_norm_count += 1
                yield norm_pair

        self._stats.pairs_generated = title_skill_count + title_norm_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["title_skill"] = title_skill_count
        self._stats.pair_types["title_normalization"] = title_norm_count

    def _generate_title_skill_pairs(
        self,
        job_title: str,
        skills: list[str],
        unique_anchors: set[str],
        unique_positives: set[str],
    ) -> Iterator[TrainingPair]:
        """Generate title-skill training pairs."""
        if not job_title or not skills:
            return

        unique_anchors.add(job_title)
        for skill in skills:
            unique_positives.add(skill)
            yield TrainingPair(
                anchor=job_title,
                positive=skill,
                source_dataset=self.info.name,
                pair_type="title_skill",
            )

    def _generate_title_normalization_pair(
        self,
        job_title: str,
        job_title_short: str,
    ) -> TrainingPair | None:
        """Create a title normalization training pair."""
        if not job_title or not job_title_short or job_title == job_title_short:
            return None

        return TrainingPair(
            anchor=job_title,
            positive=job_title_short,
            source_dataset=self.info.name,
            pair_type="title_normalization",
        )


register_adapter(DataJobsAdapter.DATASET_INFO, DataJobsAdapter)

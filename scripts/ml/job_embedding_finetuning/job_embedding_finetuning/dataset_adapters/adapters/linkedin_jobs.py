"""Adapters for LinkedIn jobs datasets (Tier 2 - Supplementary)."""

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


def _find_data_file(directory: Path) -> Path | None:
    """Find first parquet or CSV file in directory."""
    for pattern in ("*.parquet", "*.csv"):
        matches = list(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def _load_data_file(path: Path) -> pd.DataFrame:
    """Load DataFrame from parquet or CSV file."""
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


class LinkedInJobsAdapter(DatasetAdapter):
    """Adapter for HaiweiHe/linkedin-jobs dataset.

    Contains job descriptions with extracted skill labels.
    """

    DATASET_INFO = DatasetInfo(
        name="linkedin-jobs",
        hf_repo="HaiweiHe/linkedin-jobs",
        tier=DatasetTier.SUPPLEMENTARY,
        description="LinkedIn job posts with extracted skill labels",
        estimated_rows=500000,
        license="CC0-1.0",
        local_dir_name="linkedin_jobs",
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
        valid_mask = self._data["text"].notna() & self._data["label"].notna()
        self._stats.valid_rows = int(valid_mask.sum())
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate description to skill training pairs."""
        if not self._is_loaded or self._data is None:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        pairs_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            text = str(getattr(row, "text", "") or "").strip()
            labels_str = str(getattr(row, "label", "") or "").strip()

            if not text or not labels_str:
                continue

            anchor = text[:MAX_DESCRIPTION_LENGTH]
            skills = [s.strip() for s in labels_str.split(",") if s.strip()]

            if not skills:
                continue

            unique_anchors.add(anchor)

            for skill in skills:
                unique_positives.add(skill)
                pairs_count += 1
                yield TrainingPair(
                    anchor=anchor,
                    positive=skill,
                    source_dataset=self.info.name,
                    pair_type="description_skill",
                )

        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["description_skill"] = pairs_count


class LinkedInListingsAdapter(DatasetAdapter):
    """Adapter for datastax/linkedin_job_listings dataset.

    Contains job listings with title and description.
    """

    DATASET_INFO = DatasetInfo(
        name="linkedin-listings",
        hf_repo="datastax/linkedin_job_listings",
        tier=DatasetTier.SUPPLEMENTARY,
        description="LinkedIn job listings with titles and descriptions",
        estimated_rows=124000,
        local_dir_name="linkedin_listings",
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
        valid_mask = self._data["title"].notna() & self._data["description"].notna()
        self._stats.valid_rows = int(valid_mask.sum())
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate title to description training pairs."""
        if not self._is_loaded or self._data is None:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        pairs_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            title = str(getattr(row, "title", "") or "").strip()
            description = str(getattr(row, "description", "") or "").strip()

            if not title or not description:
                continue

            truncated_desc = description[:MAX_DESCRIPTION_LENGTH]

            unique_anchors.add(title)
            unique_positives.add(truncated_desc)
            pairs_count += 1

            yield TrainingPair(
                anchor=title,
                positive=truncated_desc,
                source_dataset=self.info.name,
                pair_type="title_description",
            )

        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["title_description"] = pairs_count


register_adapter(LinkedInJobsAdapter.DATASET_INFO, LinkedInJobsAdapter)
register_adapter(LinkedInListingsAdapter.DATASET_INFO, LinkedInListingsAdapter)

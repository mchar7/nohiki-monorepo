"""Adapter for lang-uk/recruitment-dataset-job-descriptions-english (Tier 2)."""

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
    """Find first parquet or CSV file in directory or data/ subdirectory."""
    search_paths = [directory, directory / "data"]
    for search_path in search_paths:
        if not search_path.exists():
            continue
        for pattern in ("*.parquet", "*.csv"):
            matches = list(search_path.glob(pattern))
            if matches:
                return matches[0]
    return None


def _load_data_file(path: Path) -> pd.DataFrame:
    """Load DataFrame from parquet or CSV file, normalizing column names."""
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    df.columns = [col.replace(" ", "_") for col in df.columns]
    return df


class LangUkRecruitmentAdapter(DatasetAdapter):
    """Adapter for lang-uk/recruitment-dataset-job-descriptions-english."""

    DATASET_INFO = DatasetInfo(
        name="lang-uk-recruitment",
        hf_repo="lang-uk/recruitment-dataset-job-descriptions-english",
        tier=DatasetTier.SUPPLEMENTARY,
        description="Tech-focused job descriptions with keywords",
        estimated_rows=142000,
        license="MIT",
        local_dir_name="lang_uk_recruitment",
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

        position_keyword_count = 0
        position_desc_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            position = str(getattr(row, "Position", "") or "").strip()
            keyword = str(getattr(row, "Primary_Keyword", "") or "").strip()
            description = str(getattr(row, "Long_Description", "") or "").strip()

            keyword_pair = self._make_keyword_pair(position, keyword, unique_anchors, unique_positives)
            if keyword_pair:
                position_keyword_count += 1
                yield keyword_pair

            desc_pair = self._make_description_pair(position, description, unique_anchors, unique_positives)
            if desc_pair:
                position_desc_count += 1
                yield desc_pair

        self._stats.pairs_generated = position_keyword_count + position_desc_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["position_keyword"] = position_keyword_count
        self._stats.pair_types["position_description"] = position_desc_count

    def _make_keyword_pair(
        self,
        position: str,
        keyword: str,
        anchors: set[str],
        positives: set[str],
    ) -> TrainingPair | None:
        """Create a position-keyword training pair."""
        if not position or not keyword:
            return None
        anchors.add(position)
        positives.add(keyword)
        return TrainingPair(
            anchor=position, positive=keyword, source_dataset=self.info.name, pair_type="position_keyword"
        )

    def _make_description_pair(
        self,
        position: str,
        description: str,
        anchors: set[str],
        positives: set[str],
    ) -> TrainingPair | None:
        """Create a position-description training pair."""
        if not position or not description:
            return None
        truncated = description[:MAX_DESCRIPTION_LENGTH]
        anchors.add(position)
        positives.add(truncated)
        return TrainingPair(
            anchor=position, positive=truncated, source_dataset=self.info.name, pair_type="position_description"
        )


register_adapter(LangUkRecruitmentAdapter.DATASET_INFO, LangUkRecruitmentAdapter)

"""Adapter for aida-ugent/JobHop dataset (Tier 1 - Core)."""

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


class JobHopAdapter(DatasetAdapter):
    """Adapter for aida-ugent/JobHop dataset.

    Contains 1.68M job transitions with ESCO taxonomy codes.
    """

    DATASET_INFO = DatasetInfo(
        name="jobhop",
        hf_repo="aida-ugent/JobHop",
        tier=DatasetTier.CORE,
        description="1.68M job transitions with ESCO taxonomy codes",
        estimated_rows=1680000,
        license="CC-BY-4.0",
        local_dir_name="jobhop",
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
        """Load the dataset from CSV or Arrow/Parquet format."""
        frames = []
        for filename in ["JobHop_train.csv", "JobHop_val.csv", "JobHop_test.csv"]:
            path = self.local_path / filename
            if path.exists():
                frames.append(pd.read_csv(path))

        # Fall back to Arrow/Parquet if no CSV files found
        if not frames:
            for pattern in ["*.parquet", "*.arrow"]:
                frames.extend(
                    pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_feather(path)
                    for path in sorted(self.local_path.glob(pattern))
                )

        if not frames:
            msg = f"No JobHop data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = pd.concat(frames, ignore_index=True)
        self._stats.total_rows = len(self._data)
        valid_mask = self._data["matched_label"].notna() & self._data["matched_description"].notna()
        self._stats.valid_rows = int(valid_mask.sum())
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate training pairs from job transitions."""
        if not self._is_loaded or self._data is None:
            msg = "Dataset not loaded. Call load() first."
            raise RuntimeError(msg)

        job_desc_count = 0
        career_count = 0
        unique_labels: set[str] = set()
        unique_descs: set[str] = set()

        for pair in self._generate_job_description_pairs():
            job_desc_count += 1
            unique_labels.add(pair.anchor)
            unique_descs.add(pair.positive)
            yield pair

        for pair in self._generate_career_progression_pairs():
            career_count += 1
            yield pair

        self._stats.pairs_generated = job_desc_count + career_count
        self._stats.unique_anchors = len(unique_labels)
        self._stats.unique_positives = len(unique_descs)
        self._stats.pair_types["job_description"] = job_desc_count
        self._stats.pair_types["career_progression"] = career_count

    def _generate_job_description_pairs(self) -> Iterator[TrainingPair]:
        if self._data is None:
            return

        for row in self._data.itertuples(index=False):
            label = str(getattr(row, "matched_label", "") or "").strip()
            description = str(getattr(row, "matched_description", "") or "").strip()

            if not label or not description or label == "nan" or description == "nan":
                continue

            yield TrainingPair(
                anchor=label,
                positive=description[:MAX_DESCRIPTION_LENGTH],
                source_dataset=self.info.name,
                pair_type="job_description",
            )

    def _generate_career_progression_pairs(self) -> Iterator[TrainingPair]:
        """Generate career pairs filtered to same ISCO minor group (3-digit prefix)."""
        if self._data is None or "person_id" not in self._data.columns:
            return

        sort_cols = ["person_id", "start_date"] if "start_date" in self._data.columns else ["person_id"]
        data = self._data.sort_values(sort_cols)

        prev_person_id = None
        prev_label: str | None = None
        prev_code: str | None = None

        for row in data.itertuples(index=False):
            person_id = getattr(row, "person_id", None)
            label = str(getattr(row, "matched_label", "") or "").strip()
            code = str(getattr(row, "matched_code", "") or "").strip()

            if not label or label == "nan":
                prev_person_id = person_id
                prev_label = None
                prev_code = None
                continue

            if person_id == prev_person_id and prev_label and prev_label != label and prev_code and code:
                prev_isco3 = _isco3_prefix(prev_code)
                curr_isco3 = _isco3_prefix(code)
                if prev_isco3 and curr_isco3 and prev_isco3 == curr_isco3:
                    yield TrainingPair(
                        anchor=prev_label,
                        positive=label,
                        source_dataset=self.info.name,
                        pair_type="career_transition",
                    )

            prev_person_id = person_id
            prev_label = label
            prev_code = code


def _isco3_prefix(esco_code: str) -> str | None:
    """Extract 3-digit ISCO prefix from ESCO code like '2512.17'."""
    isco4 = esco_code.split(".", maxsplit=1)[0]
    return isco4[:3] if len(isco4) >= 3 else None


register_adapter(JobHopAdapter.DATASET_INFO, JobHopAdapter)

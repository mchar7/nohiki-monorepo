"""Base classes for dataset adapters.

Provides abstract base class and data structures for unified
dataset handling across different sources.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_LENGTH = 512
MIN_TEXT_LENGTH = 3
ERR_NOT_LOADED = "Dataset not loaded. Call load() first."


class DatasetTier(IntEnum):
    """Dataset quality/priority tiers.

    Tier 0: Gold standard (TechWolf - JobBERT creators)
    Tier 1: Core training data (required)
    Tier 2: Supplementary data (optional)
    """

    GOLD = 0
    CORE = 1
    SUPPLEMENTARY = 2


@dataclass(frozen=True, slots=True)
class TrainingPair:
    """A single contrastive training pair.

    Attributes:
        anchor: The anchor text (e.g., job title, description).
        positive: Positive example text (similar/related to anchor).
        negative: Optional hard negative example.
        label: Similarity label (0.0 to 1.0).
        source_dataset: Name of the source dataset.
        pair_type: Type of pair (e.g., "title_skill", "job_description").

    """

    anchor: str
    positive: str
    negative: str | None = None
    label: float = 1.0
    source_dataset: str = ""
    pair_type: str = ""


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """Metadata about a dataset.

    Attributes:
        name: Unique identifier for the dataset.
        hf_repo: HuggingFace repository path.
        tier: Quality tier (0=gold, 1=core, 2=supplementary).
        description: Human-readable description.
        estimated_rows: Estimated number of rows.
        license: Dataset license.
        local_dir_name: Local directory name for downloaded data.

    """

    name: str
    hf_repo: str
    tier: DatasetTier
    description: str
    estimated_rows: int
    license: str = "Unknown"
    local_dir_name: str = ""

    def __post_init__(self) -> None:
        """Set local_dir_name from name if not provided."""
        if not self.local_dir_name:
            object.__setattr__(self, "local_dir_name", self.name.replace("-", "_"))


@dataclass(slots=True)
class DatasetStats:
    """Statistics about a loaded dataset.

    Attributes:
        total_rows: Total number of rows in the dataset.
        valid_rows: Number of valid rows after filtering.
        pairs_generated: Number of training pairs generated.
        unique_anchors: Number of unique anchor texts.
        unique_positives: Number of unique positive texts.
        pair_types: Breakdown of pairs by type.

    """

    total_rows: int = 0
    valid_rows: int = 0
    pairs_generated: int = 0
    unique_anchors: int = 0
    unique_positives: int = 0
    pair_types: dict[str, int] = field(default_factory=dict)


class DatasetAdapter(ABC):
    """Abstract base class for dataset adapters.

    Each adapter handles loading and processing a specific dataset,
    converting it to a unified TrainingPair format.

    Subclasses should define DATASET_INFO as a class variable and implement
    load() and generate_pairs() methods.
    """

    DATASET_INFO: ClassVar[DatasetInfo]

    def __init__(self, data_dir: Path) -> None:
        """Initialize the adapter with the data directory."""
        self._data_dir = data_dir
        self._is_loaded = False
        self._stats = DatasetStats()
        self._data: pd.DataFrame | None = None

    @property
    def info(self) -> DatasetInfo:
        """Return metadata about this dataset."""
        return self.DATASET_INFO

    @property
    def is_loaded(self) -> bool:
        """Check if the dataset has been loaded."""
        return self._is_loaded

    @property
    def stats(self) -> DatasetStats:
        """Return statistics about the loaded dataset."""
        return self._stats

    @property
    def local_path(self) -> Path:
        """Return the local path for this dataset."""
        return self._data_dir / self.info.local_dir_name

    def is_downloaded(self) -> bool:
        """Check if the dataset has been downloaded."""
        return self.local_path.exists() and any(self.local_path.iterdir())

    @abstractmethod
    def load(self) -> None:
        """Load the dataset from local storage."""
        ...

    @abstractmethod
    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate training pairs from this dataset."""
        ...

    def get_stats_dict(self) -> dict[str, int | str]:
        """Return statistics as a dictionary for display."""
        return {
            "total_rows": self._stats.total_rows,
            "valid_rows": self._stats.valid_rows,
            "pairs_generated": self._stats.pairs_generated,
            "unique_anchors": self._stats.unique_anchors,
            "unique_positives": self._stats.unique_positives,
        }

    def _require_loaded(self) -> pd.DataFrame:
        """Ensure dataset is loaded and return the data."""
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)
        return self._data

    def _load_file(self, filename: str) -> pd.DataFrame:
        """Load a specific file from the dataset directory."""
        path = self.local_path / filename
        if not path.exists():
            msg = f"File not found: {path}"
            raise FileNotFoundError(msg)
        return load_dataframe(path)

    def _find_and_load_data(self, patterns: list[str] | None = None) -> pd.DataFrame:
        """Find and load the first matching data file."""
        search_patterns = patterns or ["*.parquet", "*.csv", "data.*"]
        path = find_data_file(self.local_path, search_patterns)
        if path is None:
            msg = f"No data file found in {self.local_path}"
            raise FileNotFoundError(msg)
        return load_dataframe(path)

    def _set_loaded(self, data: pd.DataFrame) -> None:
        """Mark dataset as loaded and set stats."""
        self._data = data
        self._stats.total_rows = len(data)
        self._stats.valid_rows = len(data)
        self._is_loaded = True

    def _update_pair_stats(
        self,
        pairs_count: int,
        unique_anchors: set[str],
        unique_positives: set[str],
        pair_type: str,
    ) -> None:
        """Update statistics after pair generation."""
        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types[pair_type] = pairs_count

    def _create_pair(
        self,
        anchor: str,
        positive: str,
        pair_type: str,
        negative: str | None = None,
        label: float = 1.0,
    ) -> TrainingPair:
        """Create a training pair with this adapter's metadata."""
        return TrainingPair(
            anchor=anchor,
            positive=positive,
            negative=negative,
            label=label,
            source_dataset=self.info.name,
            pair_type=pair_type,
        )


def load_dataframe(path: Path) -> pd.DataFrame:
    """Load DataFrame from parquet or CSV file."""
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def find_data_file(directory: Path, patterns: list[str]) -> Path | None:
    """Find first matching data file in directory."""
    for pattern in patterns:
        matches = list(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def get_column_value(
    row: pd.Series[object],
    columns: list[str],
    default: str = "",
) -> str:
    """Get first available column value from a row."""
    for col in columns:
        if col in row.index and pd.notna(row[col]):
            return str(row[col]).strip()
    return default


def extract_skills(skills_data: object) -> list[str]:
    """Extract skill strings from various array-like formats."""
    if skills_data is None or (isinstance(skills_data, float) and pd.isna(skills_data)):
        return []
    if isinstance(skills_data, str):
        if "," in skills_data:
            return [s.strip() for s in skills_data.split(",") if s.strip()]
        return [skills_data.strip()] if skills_data.strip() else []
    if isinstance(skills_data, Iterable):
        return [str(s).strip() for s in skills_data if s and str(s).strip()]
    return []


def truncate_text(text: str, max_length: int = MAX_DESCRIPTION_LENGTH) -> str:
    """Truncate text to maximum length."""
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(" ", 1)[0] + "..."

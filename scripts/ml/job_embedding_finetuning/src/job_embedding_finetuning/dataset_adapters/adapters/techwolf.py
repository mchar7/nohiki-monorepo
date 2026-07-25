"""TechWolf dataset adapters (Tier 0 - Gold Standard)."""

from __future__ import annotations

from collections.abc import Iterable
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

ERR_NOT_LOADED = "Dataset not loaded. Call load() first."
TEST_CSV = "test.csv"
TRAIN_CSV = "train.csv"
DEV_CSV = "development.csv"
DATA_FILE_PATTERNS = ["data.csv", "dataset.csv", "data.parquet", "*.csv", "*.parquet"]


def _load_dataframe(path: Path) -> pd.DataFrame:
    """Load DataFrame from parquet or CSV."""
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _find_data_file(directory: Path, patterns: list[str]) -> Path | None:
    """Find first matching data file in directory."""
    for pattern in patterns:
        matches = list(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def _extract_skills_from_array(skills_data: object) -> list[str]:
    """Extract skill strings from various array-like formats."""
    if skills_data is None:
        return []
    if isinstance(skills_data, Iterable) and not isinstance(skills_data, str):
        return [str(s).strip() for s in skills_data if s]
    return []


class VacancyJobSkillAdapter(DatasetAdapter):
    """Adapter for TechWolf/vacancy-job-to-skill dataset."""

    DATASET_INFO = DatasetInfo(
        name="techwolf-vacancy-job-skill",
        hf_repo="TechWolf/vacancy-job-to-skill",
        tier=DatasetTier.GOLD,
        description="Job titles with ESCO-tagged skills from JobBERT creators",
        estimated_rows=5600,
        local_dir_name="techwolf_vacancy_job_skill",
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
        parquet_path = self.local_path / "job_skill_val.parquet"
        if not parquet_path.exists():
            msg = f"Dataset not found: {parquet_path}"
            raise FileNotFoundError(msg)

        self._data = pd.read_parquet(parquet_path)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data)
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate job title to skill training pairs."""
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)

        pairs_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            job_title = str(getattr(row, "vacancy_job_title", "") or "")
            skills = _extract_skills_from_array(getattr(row, "tagged_esco_skills", None))

            if not job_title or not skills:
                continue

            unique_anchors.add(job_title)

            for skill in skills:
                if not skill:
                    continue
                unique_positives.add(skill)
                pairs_count += 1
                yield TrainingPair(
                    anchor=job_title,
                    positive=skill,
                    source_dataset=self.info.name,
                    pair_type="title_skill",
                )

        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["title_skill"] = pairs_count


class SyntheticEscoAdapter(DatasetAdapter):
    """Adapter for TechWolf/Synthetic-ESCO-skill-sentences dataset.

    Contains 138K synthetic sentence-skill pairs for skill extraction.
    """

    DATASET_INFO = DatasetInfo(
        name="techwolf-synthetic-esco",
        hf_repo="TechWolf/Synthetic-ESCO-skill-sentences",
        tier=DatasetTier.GOLD,
        description="138K synthetic sentence-skill pairs for skill extraction",
        estimated_rows=138000,
        local_dir_name="techwolf_synthetic_esco",
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
        csv_path = self.local_path / "dataset.csv"
        if not csv_path.exists():
            msg = f"Dataset not found: {csv_path}"
            raise FileNotFoundError(msg)

        self._data = pd.read_csv(csv_path)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data.dropna(subset=["sentence", "skill"]))
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate sentence to skill training pairs."""
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)

        pairs_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            sentence = str(getattr(row, "sentence", "") or "").strip()
            skill = str(getattr(row, "skill", "") or "").strip()

            if not sentence or not skill:
                continue

            unique_anchors.add(sentence)
            unique_positives.add(skill)
            pairs_count += 1

            yield TrainingPair(
                anchor=sentence,
                positive=skill,
                source_dataset=self.info.name,
                pair_type="sentence_skill",
            )

        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["sentence_skill"] = pairs_count


class SkillXlAdapter(DatasetAdapter):
    """Adapter for TechWolf/Skill-XL dataset.

    Contains pre-labeled sentence-skill pairs with relevance labels.
    """

    DATASET_INFO = DatasetInfo(
        name="techwolf-skill-xl",
        hf_repo="TechWolf/Skill-XL",
        tier=DatasetTier.GOLD,
        description="Pre-labeled sentence-skill pairs with relevance labels",
        estimated_rows=6300,
        local_dir_name="techwolf_skill_xl",
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
        frames = []
        for filename in [DEV_CSV, TEST_CSV]:
            path = self.local_path / filename
            if path.exists():
                frames.append(pd.read_csv(path))

        if not frames:
            msg = f"No data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = pd.concat(frames, ignore_index=True)
        self._stats.total_rows = len(self._data)
        valid_mask = self._data["skill"].notna() & self._data["sentence"].notna()
        self._stats.valid_rows = int(valid_mask.sum())
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate sentence-skill training pairs with relevance labels."""
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)

        positive_count = 0
        negative_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            sentence = str(getattr(row, "sentence", "") or "").strip()
            skill = str(getattr(row, "skill", "") or "").strip()
            relevant = getattr(row, "relevant", 1)

            if not sentence or not skill:
                continue

            unique_anchors.add(sentence)

            if relevant == 1:
                unique_positives.add(skill)
                positive_count += 1
                yield TrainingPair(
                    anchor=sentence,
                    positive=skill,
                    label=1.0,
                    source_dataset=self.info.name,
                    pair_type="sentence_skill_positive",
                )
            else:
                negative_count += 1
                yield TrainingPair(
                    anchor=sentence,
                    positive="",
                    negative=skill,
                    label=0.0,
                    source_dataset=self.info.name,
                    pair_type="sentence_skill_negative",
                )

        total = positive_count + negative_count
        self._stats.pairs_generated = total
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["sentence_skill_positive"] = positive_count
        self._stats.pair_types["sentence_skill_negative"] = negative_count


class SkillMatchAdapter(DatasetAdapter):
    """Adapter for TechWolf/SkillMatch-1K dataset.

    Contains skill-to-skill similarity pairs - CRITICAL for skill matching benchmark.
    This is 2000 balanced pairs (1000 positive, 1000 negative).
    """

    DATASET_INFO = DatasetInfo(
        name="techwolf-skillmatch-1k",
        hf_repo="TechWolf/SkillMatch-1K",
        tier=DatasetTier.GOLD,
        description="Skill-to-skill similarity pairs (2K balanced)",
        estimated_rows=2000,
        local_dir_name="techwolf_skillmatch_1k",
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
        data_file = _find_data_file(
            self.local_path,
            [TEST_CSV, TRAIN_CSV, *DATA_FILE_PATTERNS],
        )
        if data_file is None:
            msg = f"No data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = _load_dataframe(data_file)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data)
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate skill similarity training pairs.

        Only yields POSITIVE pairs for MNRL training (in-batch negatives work best).
        The negative pairs can be used for evaluation or TripletLoss training.
        """
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)

        positive_count = 0
        negative_count = 0
        unique_skills: set[str] = set()

        col_a = "skill_a" if "skill_a" in self._data.columns else "skill1"
        col_b = "skill_b" if "skill_b" in self._data.columns else "skill2"
        col_rel = "related" if "related" in self._data.columns else "label"

        for row in self._data.itertuples(index=False):
            skill_a = str(getattr(row, col_a, "") or "").strip()
            skill_b = str(getattr(row, col_b, "") or "").strip()
            related = getattr(row, col_rel, 1)

            if not skill_a or not skill_b:
                continue

            unique_skills.add(skill_a)
            unique_skills.add(skill_b)

            # For MNRL, only yield positive pairs - negatives come from in-batch
            if related == 1 or related is True:
                positive_count += 1
                yield TrainingPair(
                    anchor=skill_a,
                    positive=skill_b,
                    label=1.0,
                    source_dataset=self.info.name,
                    pair_type="skill_similarity_positive",
                )
                # Also yield reverse direction for symmetry
                yield TrainingPair(
                    anchor=skill_b,
                    positive=skill_a,
                    label=1.0,
                    source_dataset=self.info.name,
                    pair_type="skill_similarity_positive",
                )
            else:
                negative_count += 1

        self._stats.pairs_generated = positive_count * 2  # Both directions
        self._stats.unique_anchors = len(unique_skills)
        self._stats.unique_positives = len(unique_skills)
        self._stats.pair_types["skill_similarity_positive"] = positive_count * 2
        self._stats.pair_types["skill_similarity_negative_skipped"] = negative_count


class JobBertEvalAdapter(DatasetAdapter):
    """Adapter for TechWolf/JobBERT-evaluation-dataset.

    Contains job title normalization pairs for evaluation and training.
    """

    DATASET_INFO = DatasetInfo(
        name="techwolf-jobbert-eval",
        hf_repo="TechWolf/JobBERT-evaluation-dataset",
        tier=DatasetTier.GOLD,
        description="Job title normalization pairs for evaluation and training",
        estimated_rows=31000,
        local_dir_name="techwolf_jobbert_eval",
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
        data_file = _find_data_file(
            self.local_path,
            [TEST_CSV, *DATA_FILE_PATTERNS],
        )
        if data_file is None:
            msg = f"No data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = _load_dataframe(data_file)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data)
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate job title normalization training pairs."""
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)

        pairs_count = 0
        unique_anchors: set[str] = set()
        unique_positives: set[str] = set()

        for row in self._data.itertuples(index=False):
            vacancy_title = str(getattr(row, "vacancy_job_title", "") or "").strip()
            esco_title = str(getattr(row, "esco_job_title", "") or "").strip()

            if not vacancy_title or not esco_title:
                continue

            unique_anchors.add(vacancy_title)
            unique_positives.add(esco_title)
            pairs_count += 1

            yield TrainingPair(
                anchor=vacancy_title,
                positive=esco_title,
                source_dataset=self.info.name,
                pair_type="title_normalization",
            )

        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_anchors)
        self._stats.unique_positives = len(unique_positives)
        self._stats.pair_types["title_normalization"] = pairs_count


class WorkingHistoriesAdapter(DatasetAdapter):
    """Adapter for TechWolf/anonymous-working-histories dataset.

    Contains career trajectory data for progression learning.
    """

    DATASET_INFO = DatasetInfo(
        name="techwolf-working-histories",
        hf_repo="TechWolf/anonymous-working-histories",
        tier=DatasetTier.GOLD,
        description="Career trajectory data for progression learning",
        estimated_rows=2160,
        local_dir_name="techwolf_working_histories",
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
        data_file = _find_data_file(
            self.local_path,
            ["histories.csv", *DATA_FILE_PATTERNS],
        )
        if data_file is None:
            msg = f"No data files found in {self.local_path}"
            raise FileNotFoundError(msg)

        self._data = _load_dataframe(data_file)
        self._stats.total_rows = len(self._data)
        self._stats.valid_rows = len(self._data)
        self._is_loaded = True

    def generate_pairs(self) -> Iterator[TrainingPair]:
        """Generate career progression training pairs."""
        if not self._is_loaded or self._data is None:
            raise RuntimeError(ERR_NOT_LOADED)

        pairs_count = 0
        unique_titles: set[str] = set()

        title_cols = sorted(
            [c for c in self._data.columns if c.startswith("title_")],
            key=lambda x: int(x.split("_")[1]),
        )

        for _, row in self._data.iterrows():
            titles = self._extract_valid_titles(row, title_cols)
            for pair in self._generate_progression_pairs(titles):
                pairs_count += 1
                unique_titles.add(pair.anchor)
                unique_titles.add(pair.positive)
                yield pair

        self._stats.pairs_generated = pairs_count
        self._stats.unique_anchors = len(unique_titles)
        self._stats.unique_positives = len(unique_titles)
        self._stats.pair_types["career_progression"] = pairs_count

    def _extract_valid_titles(self, row: pd.Series, title_cols: list[str]) -> list[str]:
        """Extract non-empty titles from a row."""
        titles = []
        for col in title_cols:
            val = str(getattr(row, col, "") or "").strip()
            if val and val != "nan":
                titles.append(val)
        return titles

    def _generate_progression_pairs(self, titles: list[str]) -> Iterator[TrainingPair]:
        """Generate adjacent career progression pairs."""
        for i in range(len(titles) - 1):
            yield TrainingPair(
                anchor=titles[i],
                positive=titles[i + 1],
                source_dataset=self.info.name,
                pair_type="career_progression",
            )


register_adapter(VacancyJobSkillAdapter.DATASET_INFO, VacancyJobSkillAdapter)
register_adapter(SyntheticEscoAdapter.DATASET_INFO, SyntheticEscoAdapter)
register_adapter(SkillXlAdapter.DATASET_INFO, SkillXlAdapter)
register_adapter(SkillMatchAdapter.DATASET_INFO, SkillMatchAdapter)
register_adapter(JobBertEvalAdapter.DATASET_INFO, JobBertEvalAdapter)
register_adapter(WorkingHistoriesAdapter.DATASET_INFO, WorkingHistoriesAdapter)

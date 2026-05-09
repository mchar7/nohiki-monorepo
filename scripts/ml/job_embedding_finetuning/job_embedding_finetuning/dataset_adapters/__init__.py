"""Dataset adapters for job embedding finetuning.

Provides a unified interface for loading and processing datasets
from various sources (HuggingFace, local files).
"""

from __future__ import annotations

from job_embedding_finetuning.dataset_adapters.base import (
    DatasetAdapter,
    DatasetInfo,
    DatasetTier,
    TrainingPair,
)
from job_embedding_finetuning.dataset_adapters.download import download_dataset, download_datasets_by_tier
from job_embedding_finetuning.dataset_adapters.registry import DATASET_REGISTRY, get_adapter, get_adapters_by_tier

__all__ = [
    "DATASET_REGISTRY",
    "DatasetAdapter",
    "DatasetInfo",
    "DatasetTier",
    "TrainingPair",
    "download_dataset",
    "download_datasets_by_tier",
    "get_adapter",
    "get_adapters_by_tier",
]

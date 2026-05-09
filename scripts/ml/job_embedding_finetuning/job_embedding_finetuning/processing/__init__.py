"""Data processing pipeline for training pair generation.

Provides utilities for generating, filtering, and preparing
training pairs for embedding finetuning.
"""

from __future__ import annotations

from job_embedding_finetuning.processing.filters import FilterConfig, apply_filters
from job_embedding_finetuning.processing.pair_generator import (
    PairGeneratorConfig,
    generate_all_pairs,
    generate_pairs_from_adapter,
    save_pairs_arrow,
)

__all__ = [
    "FilterConfig",
    "PairGeneratorConfig",
    "apply_filters",
    "generate_all_pairs",
    "generate_pairs_from_adapter",
    "save_pairs_arrow",
]

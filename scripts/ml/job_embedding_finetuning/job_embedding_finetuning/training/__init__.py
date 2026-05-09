"""Training module for embedding model finetuning."""

from __future__ import annotations

from .trainer import TrainingConfig, TrainingResult, run_training

__all__ = [
    "TrainingConfig",
    "TrainingResult",
    "run_training",
]

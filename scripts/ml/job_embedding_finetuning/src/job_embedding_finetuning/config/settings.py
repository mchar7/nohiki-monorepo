"""Filesystem settings with ``JEF_`` environment variable support.

Example:
    JEF_DATA_DIR=/custom/path
    JEF_OUTPUT_DIR=/custom/output
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from job_embedding_finetuning.config.defaults import OUTPUT_DIR, TRAINING_DATA_DIR


class Settings(BaseSettings):
    """Filesystem settings overridden through the ``JEF_`` prefix."""

    model_config = SettingsConfigDict(
        env_prefix="JEF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(
        default=TRAINING_DATA_DIR,
        description="Directory for downloaded training datasets",
    )
    output_dir: Path = Field(
        default=OUTPUT_DIR,
        description="Directory for training outputs (models, checkpoints, logs)",
    )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

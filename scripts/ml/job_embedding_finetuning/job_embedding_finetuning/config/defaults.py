"""Filesystem paths for job embedding finetuning."""

from __future__ import annotations

from pathlib import Path
from typing import Final

# Path constants
SCRIPT_DIR: Final[Path] = Path(__file__).resolve().parent.parent
TRAINING_DATA_DIR: Final[Path] = SCRIPT_DIR / "training_data"
OUTPUT_DIR: Final[Path] = SCRIPT_DIR / "output"

# Tabiya ESCO data directory (committed to repo root)
TABIYA_DATA_DIR: Final[Path] = Path(__file__).resolve().parents[5] / "data" / "tabiya"

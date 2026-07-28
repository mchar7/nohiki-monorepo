"""Skill Threshold Calibration CLI.

Empirically calibrates auto-canonicalization thresholds for the skill normalization
pipeline using real Tabiya/ESCO taxonomy data (~97K skills).

Usage:
    uv run python -m calibrate_skill_thresholds --help
    uv run python -m calibrate_skill_thresholds analyze --csv-path data/tabiya/skills.csv
    uv run python -m calibrate_skill_thresholds report --input calibration_results.json
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "CalibrationDataset",
    "JaccardAnalyzer",
    "TabiyaLoader",
]

from calibrate_skill_thresholds.analysis import JaccardAnalyzer
from calibrate_skill_thresholds.data import CalibrationDataset, TabiyaLoader

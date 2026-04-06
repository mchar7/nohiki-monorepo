"""Calibration provenance models for ML encoder normalization constants.

Calibration provenance records how normalization constants were derived:
which dataset, how many samples, and when.  Separated from operational
config so model identity (model_id, thresholds) can evolve independently
of calibration history.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class BaseCalibrationConfig(BaseModel):
    """Base calibration provenance shared by all encoder types.

    Tracks the model used during calibration, sample size, and date.
    Subclasses add encoder-specific calibration metrics.
    """

    calibration_model_id: str = Field(
        description="Model ID used during calibration",
    )
    calibration_pairs_count: int = Field(
        ge=1,
        description="Number of sample pairs used for calibration",
    )
    calibration_date: date = Field(
        description="Date of calibration run",
    )


class MaxSimCalibrationConfig(BaseCalibrationConfig):
    """Calibration provenance for ColBERT MaxSim per-token statistics.

    Records the empirical basis for the normalization constants in
    MaxSimNormalizationConfig (per_token_sim_mean, per_token_sim_std, etc.).
    """


class DenseCalibrationConfig(BaseCalibrationConfig):
    """Calibration provenance for dense embedding similarity thresholds.

    Records the empirical basis for the operational thresholds in
    DenseNormalizationConfig (auto_match_threshold, uncertain_min_threshold).
    Thresholds calibrated from skill-to-skill similarity pairs where
    auto_match_threshold is chosen at precision=100% (zero false positives).
    """

    max_fp_similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Highest similarity score observed on a false positive pair",
    )

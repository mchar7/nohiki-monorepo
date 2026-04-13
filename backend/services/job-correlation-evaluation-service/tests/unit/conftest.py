"""Unit test fixtures for job-correlation-evaluation-service."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import lightgbm as lgb
import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.constants import FEATURE_COUNT

if TYPE_CHECKING:
    from collections.abc import Generator

# Deterministic RNG for reproducible synthetic model
_RNG = np.random.default_rng(42)


@pytest.fixture(scope="session")
def synthetic_l2r_model_dir() -> Generator[Path]:
    """Generate a synthetic LightGBM model with FEATURE_COUNT features.

    Creates a minimal LightGBM regression model and a min_max calibrator
    in a temporary directory. Used by tests that need a model file matching
    the current FEATURE_COUNT (which may differ from the checked-in model).

    Yields:
        Path to temporary directory containing l2r_lightgbm.txt and
        calibrator.joblib.
    """
    with tempfile.TemporaryDirectory(prefix="l2r_test_") as tmpdir:
        tmp_path = Path(tmpdir)
        model_path = tmp_path / "l2r_lightgbm.txt"
        calibrator_path = tmp_path / "calibrator.joblib"

        # Train a tiny model with the correct feature count
        n_samples = 200
        x = _RNG.random((n_samples, FEATURE_COUNT)).astype(np.float32)
        y = _RNG.random(n_samples)
        ds = lgb.Dataset(x, label=y, free_raw_data=False)
        model = lgb.train(
            {"objective": "regression", "verbose": -1, "num_iterations": 5},
            ds,
        )
        model.save_model(str(model_path))

        # Create a min_max calibrator (compatible with IsotonicCalibrator.load)
        calibrator_data = {
            "type": "min_max",
            "version": "1.0.0-test",
            "min_raw": -2.0,
            "max_raw": 2.0,
            "target_min": 0.05,
            "target_max": 0.95,
        }
        joblib.dump(calibrator_data, calibrator_path)

        yield tmp_path

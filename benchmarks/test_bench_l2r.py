"""Benchmarks for L2R scoring pipeline (LightGBM predict + isotonic calibration).

These benchmarks exercise the actual LightGBM model and calibrator files
stored in models/l2r/. They measure:
- Single prediction latency
- Batch prediction throughput (150 candidates typical, 1000 max)
- Calibration overhead (isotonic regression transform)
- Full score_and_calibrate pipeline

The L2RScorer is loaded via importlib to bypass the service's scoring/__init__.py
which eagerly imports the full service tree (including nohiki-ml-core heavy dep).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import numpy as np
import pytest

if TYPE_CHECKING:
    from numpy.typing import NDArray

from nohiki_ml_manifest.features import FEATURE_COUNT

MODELS_DIR = Path(__file__).resolve().parent.parent / "models" / "l2r"
MODEL_PATH = MODELS_DIR / "l2r_lightgbm.txt"
CALIBRATOR_PATH = MODELS_DIR / "calibrator.joblib"

# Direct module loading to avoid the scoring/__init__.py import chain
_SERVICE_SRC = (
    Path(__file__).resolve().parent.parent / "backend" / "services" / "job-correlation-evaluation-service" / "src"
)


def _load_scorer_class() -> type:
    """Load L2RScorer class directly without triggering scoring/__init__.py."""
    # Load calibrator module first (dependency of scorer)
    calibrator_path = (
        _SERVICE_SRC / "job_correlation_evaluation_service" / "services" / "scoring" / "l2r" / "calibrator.py"
    )
    spec_cal = importlib.util.spec_from_file_location(
        "job_correlation_evaluation_service.services.scoring.l2r.calibrator",
        calibrator_path,
    )
    if spec_cal is None or spec_cal.loader is None:
        msg = f"Cannot load calibrator module from {calibrator_path}"
        raise ImportError(msg)
    mod_cal = importlib.util.module_from_spec(spec_cal)
    sys.modules[spec_cal.name] = mod_cal
    spec_cal.loader.exec_module(mod_cal)

    # Load exceptions module (dependency of scorer)
    exceptions_path = (
        _SERVICE_SRC / "job_correlation_evaluation_service" / "services" / "scoring" / "l2r" / "exceptions.py"
    )
    spec_exc = importlib.util.spec_from_file_location(
        "job_correlation_evaluation_service.services.scoring.l2r.exceptions",
        exceptions_path,
    )
    if spec_exc is None or spec_exc.loader is None:
        msg = f"Cannot load exceptions module from {exceptions_path}"
        raise ImportError(msg)
    mod_exc = importlib.util.module_from_spec(spec_exc)
    sys.modules[spec_exc.name] = mod_exc
    spec_exc.loader.exec_module(mod_exc)

    # Load scorer module
    scorer_path = _SERVICE_SRC / "job_correlation_evaluation_service" / "services" / "scoring" / "l2r" / "scorer.py"
    spec_scorer = importlib.util.spec_from_file_location(
        "job_correlation_evaluation_service.services.scoring.l2r.scorer",
        scorer_path,
    )
    if spec_scorer is None or spec_scorer.loader is None:
        msg = f"Cannot load scorer module from {scorer_path}"
        raise ImportError(msg)
    mod_scorer = importlib.util.module_from_spec(spec_scorer)
    sys.modules[spec_scorer.name] = mod_scorer
    spec_scorer.loader.exec_module(mod_scorer)

    return mod_scorer.L2RScorer


@pytest.fixture
def scorer() -> object:
    """Load the real L2R scorer with model and calibrator."""
    if not MODEL_PATH.exists() or not CALIBRATOR_PATH.exists():
        pytest.skip("L2R model files not available")

    l2r_scorer_cls = _load_scorer_class()
    settings = MagicMock()
    settings.l2r_model_path = str(MODEL_PATH)
    settings.l2r_calibrator_path = str(CALIBRATOR_PATH)
    s = l2r_scorer_cls(settings)
    s.load()
    return s


# Single prediction


def test_bench_l2r_score_single(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark single feature vector scoring (LightGBM predict)."""
    rng = np.random.default_rng(42)
    features = rng.standard_normal(FEATURE_COUNT).astype(np.float32)
    benchmark(scorer.score, features)


def test_bench_l2r_calibrate_single(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark single score calibration (isotonic transform)."""
    benchmark(scorer.calibrate, 0.65)


def test_bench_l2r_score_and_calibrate_single(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark full single scoring pipeline: predict + calibrate + to_100."""
    rng = np.random.default_rng(42)
    features = rng.standard_normal(FEATURE_COUNT).astype(np.float32)
    benchmark(scorer.score_and_calibrate, features)


# Batch prediction (typical pipeline sizes)


def _make_batch(n: int) -> NDArray[np.float32]:
    """Create a batch of random feature vectors."""
    rng = np.random.default_rng(42)
    return rng.standard_normal((n, FEATURE_COUNT)).astype(np.float32)


def test_bench_l2r_score_batch_50(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark batch scoring: 50 candidates (post-LLM rerank)."""
    batch = _make_batch(50)
    benchmark(scorer.score_batch, batch)


def test_bench_l2r_score_batch_150(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark batch scoring: 150 candidates (typical Stage 2 output)."""
    batch = _make_batch(150)
    benchmark(scorer.score_batch, batch)


def test_bench_l2r_score_batch_1000(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark batch scoring: 1000 candidates (Stage 1 output)."""
    batch = _make_batch(1000)
    benchmark(scorer.score_batch, batch)


def test_bench_l2r_calibrate_batch_150(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark batch calibration: 150 raw scores."""
    rng = np.random.default_rng(42)
    raw_scores = rng.uniform(-2.0, 2.0, size=150).astype(np.float64)
    benchmark(scorer.calibrate_batch, raw_scores)


def test_bench_l2r_full_pipeline_batch_150(
    benchmark: pytest.BenchmarkFixture,
    scorer: object,
) -> None:
    """Benchmark full batch pipeline: predict + calibrate + to_100 for 150 candidates."""
    batch = _make_batch(150)
    benchmark(scorer.score_and_calibrate_batch, batch)

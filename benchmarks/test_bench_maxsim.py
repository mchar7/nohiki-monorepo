"""Benchmarks for MaxSim normalization and computation.

These are the pure-math hot paths in the scoring pipeline:
- normalize_maxsim_score_absolute: called per-candidate per scoring run
- Full MaxSim matrix computation: NumPy cosine similarity matrix

The normalize functions are inlined here to avoid importing the service
package tree, which transitively requires nohiki-ml-core (heavy optional dep).
The implementations are exact copies from native_maxsim.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from numpy.typing import NDArray

_MIN_EXPECTED_STD = 0.001


def _normalize_maxsim_score_absolute(
    raw_maxsim: float,
    num_tokens: int,
    per_token_mean: float,
    per_token_std: float,
) -> float:
    """Normalize a single MaxSim score using model-intrinsic constants.

    Exact copy of native_maxsim.normalize_maxsim_score_absolute to avoid
    triggering the service's heavy import chain.
    """
    if num_tokens <= 0:
        return 0.5
    expected = num_tokens * per_token_mean
    expected_std = (num_tokens**0.5) * per_token_std
    if expected_std < _MIN_EXPECTED_STD:
        return 0.5
    z_score = (raw_maxsim - expected) / expected_std
    normalized = 0.5 + 0.5 * (z_score / (1.0 + abs(z_score) * 0.5))
    return max(0.0, min(1.0, normalized))


@dataclass(frozen=True, slots=True)
class _CandidateStub:
    """Lightweight stand-in for MultiStageSearchResult in benchmarks."""

    id: str
    maxsim_score: float


def _normalize_maxsim_scores(
    candidates: list[_CandidateStub],
    num_tokens: int,
    per_token_mean: float = 0.9355,
    per_token_std: float = 0.0396,
) -> list[float]:
    """Normalize MaxSim scores for a batch of candidates.

    Exact copy of native_maxsim.normalize_maxsim_scores logic.
    """
    if not candidates:
        return []
    return [
        _normalize_maxsim_score_absolute(c.maxsim_score, num_tokens, per_token_mean, per_token_std) for c in candidates
    ]


# MaxSim normalization (pure math, called per-candidate)


def test_bench_normalize_single_score(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark single MaxSim score normalization."""
    benchmark(
        _normalize_maxsim_score_absolute,
        raw_maxsim=28.7,
        num_tokens=32,
        per_token_mean=0.9355,
        per_token_std=0.0396,
    )


def test_bench_normalize_batch_150(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark batch normalization for 150 candidates (typical Stage 2 output)."""
    rng = np.random.default_rng(42)
    candidates = [_CandidateStub(id=f"entity-{i}", maxsim_score=float(rng.uniform(20.0, 35.0))) for i in range(150)]
    benchmark(
        _normalize_maxsim_scores,
        candidates=candidates,
        num_tokens=32,
        per_token_mean=0.9355,
        per_token_std=0.0396,
    )


def test_bench_normalize_batch_1000(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark batch normalization for 1000 candidates (Stage 1 output)."""
    rng = np.random.default_rng(42)
    candidates = [_CandidateStub(id=f"entity-{i}", maxsim_score=float(rng.uniform(20.0, 35.0))) for i in range(1000)]
    benchmark(
        _normalize_maxsim_scores,
        candidates=candidates,
        num_tokens=32,
        per_token_mean=0.9355,
        per_token_std=0.0396,
    )


# Full MaxSim computation (NumPy matrix multiply + max reduction)


def _compute_maxsim_inline(
    query_tokens: NDArray[np.float32],
    doc_tokens: NDArray[np.float32],
) -> float:
    """Reproduce the inline MaxSim computation from ScoringPipeline._compute_maxsim."""
    query_norm = query_tokens / (np.linalg.norm(query_tokens, axis=1, keepdims=True) + 1e-9)
    doc_norm = doc_tokens / (np.linalg.norm(doc_tokens, axis=1, keepdims=True) + 1e-9)
    sim_matrix = query_norm @ doc_norm.T
    max_sims = sim_matrix.max(axis=1)
    return float(max_sims.sum())


def test_bench_maxsim_matrix_32x128(
    benchmark: pytest.BenchmarkFixture,
    colbert_query_tokens: NDArray[np.float32],
    colbert_doc_tokens: NDArray[np.float32],
) -> None:
    """Benchmark MaxSim: 32 query tokens vs 128 doc tokens (typical sizes)."""
    benchmark(_compute_maxsim_inline, colbert_query_tokens, colbert_doc_tokens)


def test_bench_maxsim_matrix_32x256(
    benchmark: pytest.BenchmarkFixture,
    rng: np.random.Generator,
) -> None:
    """Benchmark MaxSim: 32 query tokens vs 256 doc tokens (long document)."""
    query = rng.standard_normal((32, 48)).astype(np.float32)
    doc = rng.standard_normal((256, 48)).astype(np.float32)
    benchmark(_compute_maxsim_inline, query, doc)


def test_bench_maxsim_matrix_64x128(
    benchmark: pytest.BenchmarkFixture,
    rng: np.random.Generator,
) -> None:
    """Benchmark MaxSim: 64 query tokens vs 128 doc tokens (long query)."""
    query = rng.standard_normal((64, 48)).astype(np.float32)
    doc = rng.standard_normal((128, 48)).astype(np.float32)
    benchmark(_compute_maxsim_inline, query, doc)

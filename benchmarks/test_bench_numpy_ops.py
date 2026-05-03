"""Benchmarks for NumPy-heavy operations in the scoring pipeline.

These operations are called per-candidate or per-batch in the L2R pipeline:
- Feature vector allocation and NaN-fill
- Vector normalization (L2 norm)
- Cosine similarity matrix computation
- Batch stacking and score conversion
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from numpy.typing import NDArray

from nohiki_ml_manifest.features import FEATURE_COUNT

# Feature vector allocation (called per-candidate in FeatureComposer.extract)


def test_bench_feature_vector_alloc_nanfill(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark np.full(FEATURE_COUNT, nan) -- called once per candidate."""
    benchmark(np.full, FEATURE_COUNT, math.nan, np.float32)


def test_bench_feature_vector_zeros(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark np.zeros alternative for comparison."""
    benchmark(np.zeros, FEATURE_COUNT, np.float32)


# Vector normalization (L2 norm, called in MaxSim computation)


def test_bench_l2_normalize_32x48(
    benchmark: pytest.BenchmarkFixture,
    colbert_query_tokens: NDArray[np.float32],
) -> None:
    """Benchmark L2 normalization of 32x48 token matrix."""

    def normalize(tokens: NDArray[np.float32]) -> NDArray[np.float32]:
        norms = np.linalg.norm(tokens, axis=1, keepdims=True)
        return tokens / (norms + 1e-9)

    benchmark(normalize, colbert_query_tokens)


def test_bench_l2_normalize_128x48(
    benchmark: pytest.BenchmarkFixture,
    colbert_doc_tokens: NDArray[np.float32],
) -> None:
    """Benchmark L2 normalization of 128x48 token matrix."""

    def normalize(tokens: NDArray[np.float32]) -> NDArray[np.float32]:
        norms = np.linalg.norm(tokens, axis=1, keepdims=True)
        return tokens / (norms + 1e-9)

    benchmark(normalize, colbert_doc_tokens)


# Matrix multiplication (cosine similarity matrix, core of MaxSim)


def test_bench_matmul_32x48_by_48x128(
    benchmark: pytest.BenchmarkFixture,
    colbert_query_tokens: NDArray[np.float32],
    colbert_doc_tokens: NDArray[np.float32],
) -> None:
    """Benchmark query @ doc.T matrix multiplication (32x48 @ 48x128 = 32x128)."""
    benchmark(np.matmul, colbert_query_tokens, colbert_doc_tokens.T)


def test_bench_matmul_64x48_by_48x256(
    benchmark: pytest.BenchmarkFixture,
    rng: np.random.Generator,
) -> None:
    """Benchmark larger matrix multiply (64x48 @ 48x256 = 64x256)."""
    query = rng.standard_normal((64, 48)).astype(np.float32)
    doc = rng.standard_normal((256, 48)).astype(np.float32)
    benchmark(np.matmul, query, doc.T)


# Batch operations (stacking feature vectors, score conversion)


def test_bench_stack_150_feature_vectors(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark np.stack for 150 feature vectors (typical batch)."""
    rng = np.random.default_rng(42)
    vectors = [rng.standard_normal(FEATURE_COUNT).astype(np.float32) for _ in range(150)]
    benchmark(np.stack, vectors)


def test_bench_stack_1000_feature_vectors(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark np.stack for 1000 feature vectors (large batch)."""
    rng = np.random.default_rng(42)
    vectors = [rng.standard_normal(FEATURE_COUNT).astype(np.float32) for _ in range(1000)]
    benchmark(np.stack, vectors)


def test_bench_score_to_100_batch(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark calibrated probability to 0-100 integer conversion."""
    rng = np.random.default_rng(42)
    calibrated = rng.uniform(0.0, 1.0, size=150).astype(np.float64)

    def to_score_100(probs: NDArray[np.float64]) -> NDArray[np.int_]:
        return np.round(probs * 100).astype(np.int_)

    benchmark(to_score_100, calibrated)


# MUVERA FDE vector operations


def test_bench_muvera_cosine_similarity(
    benchmark: pytest.BenchmarkFixture,
    muvera_fde_vector: NDArray[np.float32],
    rng: np.random.Generator,
) -> None:
    """Benchmark cosine similarity between two 8192-dim MUVERA vectors."""
    other = rng.standard_normal(8192).astype(np.float32)
    other = other / (np.linalg.norm(other) + 1e-9)

    def cosine_sim(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
        return float(np.dot(a, b))

    benchmark(cosine_sim, muvera_fde_vector, other)

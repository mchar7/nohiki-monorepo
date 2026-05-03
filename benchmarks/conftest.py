"""Shared fixtures for performance benchmarks."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from numpy.typing import NDArray


@pytest.fixture
def rng() -> np.random.Generator:
    """Seeded random generator for reproducible benchmark data."""
    return np.random.default_rng(seed=42)


@pytest.fixture
def colbert_query_tokens(rng: np.random.Generator) -> NDArray[np.float32]:
    """Realistic ColBERT query tokens: 32 tokens x 48 dimensions."""
    tokens = rng.standard_normal((32, 48)).astype(np.float32)
    norms = np.linalg.norm(tokens, axis=1, keepdims=True)
    return tokens / (norms + 1e-9)


@pytest.fixture
def colbert_doc_tokens(rng: np.random.Generator) -> NDArray[np.float32]:
    """Realistic ColBERT document tokens: 128 tokens x 48 dimensions."""
    tokens = rng.standard_normal((128, 48)).astype(np.float32)
    norms = np.linalg.norm(tokens, axis=1, keepdims=True)
    return tokens / (norms + 1e-9)


@pytest.fixture
def feature_vector_single(rng: np.random.Generator) -> NDArray[np.float32]:
    """Single 31-dimension feature vector with realistic values."""
    return rng.standard_normal(31).astype(np.float32)


@pytest.fixture
def feature_matrix_batch(rng: np.random.Generator) -> NDArray[np.float32]:
    """Batch of 150 feature vectors (typical pipeline output)."""
    return rng.standard_normal((150, 31)).astype(np.float32)


@pytest.fixture
def muvera_fde_vector(rng: np.random.Generator) -> NDArray[np.float32]:
    """MUVERA FDE vector: 8192 dimensions."""
    vec = rng.standard_normal(8192).astype(np.float32)
    return vec / (np.linalg.norm(vec) + 1e-9)

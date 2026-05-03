"""Benchmarks for embedding client operations (nohiki-embedding-client).

Measures EmbeddingSpec/EmbeddingResult dataclass construction,
exception hierarchy, and type lookup -- operations that run on every
embedding request and callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from nohiki_embedding_client.exceptions import (
    EmbeddingError,
    EmbeddingFailedError,
    EmbeddingTimeoutError,
)

# Inline EmbeddingSpec/Result stubs (avoid importing heavy protobuf deps)

_EMBEDDING_TYPES = ("DENSE", "MUVERA", "COLBERT", "SPARSE")


@dataclass(frozen=True, slots=True)
class _EmbeddingSpec:
    """Inlined from nohiki_embedding_client.types."""

    embedding_type: str
    encoding_mode: str = "DOCUMENT"
    publish_to_index: bool = True


@dataclass(slots=True)
class _EmbeddingVector:
    """Inlined embedding vector stub."""

    embedding_type: str
    values: list[float] = field(default_factory=list)
    dimension: int = 0


@dataclass(slots=True)
class _EmbeddingResult:
    """Inlined from nohiki_embedding_client.types."""

    request_id: str
    entity_id: str
    vectors: list[_EmbeddingVector] = field(default_factory=list)

    def get_by_type(self, embedding_type: str) -> _EmbeddingVector | None:
        """Look up vector by type -- O(n) scan."""
        for v in self.vectors:
            if v.embedding_type == embedding_type:
                return v
        return None


# EmbeddingSpec construction (every embedding request)


def test_bench_embedding_spec_dense(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a DENSE embedding spec."""
    benchmark(_EmbeddingSpec, embedding_type="DENSE")


def test_bench_embedding_spec_colbert(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a COLBERT embedding spec."""
    benchmark(_EmbeddingSpec, embedding_type="COLBERT", encoding_mode="QUERY")


def test_bench_embedding_spec_no_publish(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating spec with publish_to_index=False."""
    benchmark(
        _EmbeddingSpec,
        embedding_type="MUVERA",
        publish_to_index=False,
    )


# EmbeddingResult construction and lookup (every callback)

_SAMPLE_VECTORS = [
    _EmbeddingVector(embedding_type="DENSE", values=[0.1] * 1024, dimension=1024),
    _EmbeddingVector(embedding_type="MUVERA", values=[0.2] * 8192, dimension=8192),
    _EmbeddingVector(embedding_type="SPARSE", values=[0.3] * 50, dimension=50),
]


def test_bench_embedding_result_construction(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark constructing an EmbeddingResult with 3 vectors."""
    benchmark(
        _EmbeddingResult,
        request_id="req-123",
        entity_id="entity-456",
        vectors=_SAMPLE_VECTORS,
    )


def test_bench_get_by_type_first(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark get_by_type hitting first element (best case)."""
    result = _EmbeddingResult(
        request_id="req-123",
        entity_id="entity-456",
        vectors=_SAMPLE_VECTORS,
    )
    benchmark(result.get_by_type, "DENSE")


def test_bench_get_by_type_last(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark get_by_type hitting last element (worst case, 3 items)."""
    result = _EmbeddingResult(
        request_id="req-123",
        entity_id="entity-456",
        vectors=_SAMPLE_VECTORS,
    )
    benchmark(result.get_by_type, "SPARSE")


def test_bench_get_by_type_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark get_by_type with no match (full scan)."""
    result = _EmbeddingResult(
        request_id="req-123",
        entity_id="entity-456",
        vectors=_SAMPLE_VECTORS,
    )
    benchmark(result.get_by_type, "COLBERT")


# Exception hierarchy (every error path in embedding pipeline)


def test_bench_embedding_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a base EmbeddingError."""
    benchmark(
        EmbeddingError,
        "Embedding failed",
        request_id="req-123",
        entity_id="entity-456",
    )


def test_bench_embedding_timeout(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating an EmbeddingTimeoutError."""
    benchmark(EmbeddingTimeoutError, "req-123", 30.0, entity_id="entity-456")


def test_bench_embedding_failed_retryable(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a retryable EmbeddingFailedError."""
    benchmark(
        EmbeddingFailedError,
        "req-123",
        "GPU OOM",
        "RESOURCE_EXHAUSTED",
        entity_id="entity-456",
        retryable=True,
    )


def test_bench_embedding_failed_not_retryable(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark creating a non-retryable EmbeddingFailedError."""
    benchmark(
        EmbeddingFailedError,
        "req-123",
        "Invalid input",
        "INVALID_INPUT",
        entity_id="entity-456",
        retryable=False,
    )


def test_bench_embedding_error_is_retryable(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark checking is_retryable on embedding exception."""
    err = EmbeddingTimeoutError("req-123", 30.0)
    benchmark(lambda: err.is_retryable)


def test_bench_embedding_error_isinstance(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark isinstance check for error hierarchy dispatch."""
    err = EmbeddingTimeoutError("req-123", 30.0)
    benchmark(lambda: isinstance(err, EmbeddingError))

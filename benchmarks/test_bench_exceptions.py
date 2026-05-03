"""Benchmarks for exception creation and classification (nohiki-common-exceptions).

Typed exceptions are created on every error path in Kafka handlers.
The to_log_context() and is_retryable checks run on every exception.
"""

from __future__ import annotations

import pytest
from nohiki_common_exceptions import (
    DataNotAvailableError,
    DataNotFoundError,
    ExternalServiceError,
    NohikiError,
    RateLimitedError,
    RetryStrategy,
    SchemaVersionMismatchError,
    StaleDataError,
    ValidationError,
)

# Exception construction


def test_bench_create_data_not_found(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark DataNotFoundError construction (most common error type)."""
    benchmark(
        DataNotFoundError,
        resource_type="Listing",
        resource_id="550e8400-e29b-41d4-a716-446655440000",
    )


def test_bench_create_data_not_available(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark DataNotAvailableError construction (retryable)."""
    benchmark(
        DataNotAvailableError,
        resource_type="EmbeddingVector",
        resource_id="pref-12345",
        source="qdrant",
    )


def test_bench_create_validation_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ValidationError construction (input validation failures)."""
    benchmark(
        ValidationError,
        message="Invalid listing snapshot: missing required field 'title'",
    )


def test_bench_create_external_service_error(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark ExternalServiceError construction."""
    benchmark(
        ExternalServiceError,
        service_name="openrouter",
        operation="chat_completion",
        message="HTTP 503 Service Unavailable",
    )


def test_bench_create_rate_limited_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark RateLimitedError construction."""
    benchmark(
        RateLimitedError,
        service_name="openrouter",
        retry_after_seconds=30,
    )


def test_bench_create_stale_data_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark StaleDataError construction (data freshness check)."""
    benchmark(
        StaleDataError,
        resource_type="SearchPref",
        resource_id="pref-12345",
        data_age_seconds=3600.0,
        max_age_seconds=1800.0,
    )


def test_bench_create_schema_mismatch_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark SchemaVersionMismatchError construction."""
    benchmark(
        SchemaVersionMismatchError,
        expected_version="v1",
        actual_version="v2",
    )


# Exception property access (hot path in error handling)


def test_bench_is_retryable_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark is_retryable property (checked on every exception)."""
    err = DataNotAvailableError(
        resource_type="Listing",
        resource_id="test-id",
        source="cache",
    )
    benchmark(lambda: err.is_retryable)


def test_bench_to_log_context(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark to_log_context() (called for structured logging on errors)."""
    err = DataNotFoundError(
        resource_type="Listing",
        resource_id="550e8400-e29b-41d4-a716-446655440000",
    )
    benchmark(err.to_log_context)


def test_bench_retry_strategy_comparison(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark retry strategy enum comparison (DLQ routing decision)."""
    err = ExternalServiceError(
        service_name="openrouter",
        operation="chat_completion",
        message="timeout",
    )

    def classify() -> str:
        if err.retry_strategy == RetryStrategy.NO_RETRY:
            return "dlq"
        if err.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL:
            return "retry_exp"
        if err.retry_strategy == RetryStrategy.RETRY_LINEAR:
            return "retry_linear"
        return "retry_immediate"

    benchmark(classify)


# Exception hierarchy traversal (isinstance checks in handlers)


def test_bench_isinstance_nohiki_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark isinstance check against base NohikiError."""
    err = DataNotFoundError(
        resource_type="Listing",
        resource_id="test-id",
    )
    benchmark(isinstance, err, NohikiError)


def test_bench_exception_chain_classify(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full exception classification chain (typical handler pattern)."""
    err = DataNotAvailableError(
        resource_type="Listing",
        resource_id="test-id",
        source="cache",
    )

    def classify() -> str:
        if isinstance(err, DataNotFoundError):
            return "not_found"
        if isinstance(err, DataNotAvailableError):
            return "not_available"
        if isinstance(err, ValidationError):
            return "validation"
        if isinstance(err, ExternalServiceError):
            return "external"
        return "unknown"

    benchmark(classify)

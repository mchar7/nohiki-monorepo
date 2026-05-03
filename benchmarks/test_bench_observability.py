"""Benchmarks for observability infrastructure (nohiki-observability).

Structured logging and correlation ID operations are called on every
single request and event handler invocation. Even tiny per-call overhead
adds up at scale.
"""

from __future__ import annotations

import logging
import uuid

import pytest
import structlog
from nohiki_observability import get_correlation_id, get_logger, set_correlation_id

# Structured logging (structlog + get_logger)


def test_bench_get_logger(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark get_logger() call (module-level logger creation)."""
    benchmark(get_logger, "benchmarks.test_module")


def test_bench_structlog_bind(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark structlog context binding (called per-request/event)."""
    logger = get_logger("benchmarks.test_bind")

    def bind() -> structlog.stdlib.BoundLogger:
        return logger.bind(
            request_id="req-12345",
            user_id="user-67890",
            service="test-service",
        )

    benchmark(bind)


def test_bench_structlog_log_debug(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark debug log call (typically filtered out in production)."""
    logger = get_logger("benchmarks.test_debug")
    logger = logger.bind(service="test-service")

    logging.getLogger("benchmarks.test_debug").setLevel(logging.WARNING)

    benchmark(logger.debug, "Debug message", key="value", count=42)


def test_bench_structlog_log_info(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark info log call with context."""
    logger = get_logger("benchmarks.test_info")
    logger = logger.bind(service="test-service")

    benchmark(
        logger.info,
        "Processing event",
        topic="job-listing.cdc.listing-created.v1",
        partition=3,
        offset=12345,
    )


def test_bench_structlog_log_with_exception(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark error log call with exception context."""
    logger = get_logger("benchmarks.test_error")
    exc = ValueError("Test exception for benchmarking")

    benchmark(
        logger.error,
        "Handler failed",
        exc_info=exc,
        topic="test.topic",
        retry_count=2,
    )


# Correlation ID operations (ContextVar-based)


def test_bench_set_correlation_id(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark set_correlation_id (called per incoming request/event)."""
    cid = "corr-550e8400-e29b-41d4-a716-446655440000"
    benchmark(set_correlation_id, cid)


def test_bench_get_correlation_id(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark get_correlation_id (called for every log entry and publish)."""
    set_correlation_id("corr-550e8400-e29b-41d4-a716-446655440000")
    benchmark(get_correlation_id)


def test_bench_correlation_id_roundtrip(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark set + get correlation ID (full request lifecycle)."""

    def roundtrip() -> str | None:
        cid = str(uuid.uuid4())
        set_correlation_id(cid)
        return get_correlation_id()

    benchmark(roundtrip)


# UUID generation (used for event_id, correlation_id)


def test_bench_uuid4_generation(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark uuid4 generation (called per event publish)."""
    benchmark(uuid.uuid4)


def test_bench_uuid4_to_string(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark uuid4 generation + string conversion."""

    def gen() -> str:
        return str(uuid.uuid4())

    benchmark(gen)

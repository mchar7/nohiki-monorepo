"""Benchmarks for Kafka client internals (nohiki-kafka-client).

Measures topic routing, event metadata creation, DLQ classification,
and handler dispatch patterns -- operations that execute on every
consumed Kafka message.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

import pytest
from nohiki_kafka_client.topics import Topics

# Topic routing (handler dispatch on every message)

_TOPIC_TO_HANDLER: dict[str, str] = {
    Topics.JOB_LISTING_CREATED: "handle_listing_created",
    Topics.JOB_LISTING_UPDATED: "handle_listing_updated",
    Topics.JOB_LISTING_DELETED: "handle_listing_deleted",
    Topics.USER_PREF_CREATED: "handle_pref_created",
    Topics.USER_PREF_UPDATED: "handle_pref_updated",
    Topics.ML_EMBEDDING_COMPLETED: "handle_embedding_completed",
    Topics.JOB_CORRELATION_EVALUATED: "handle_correlation_evaluated",
    Topics.DOC_TEMPLATE_RENDER_COMPLETED: "handle_render_completed",
    Topics.NOTIFICATION_SENT: "handle_notification_sent",
    Topics.SYS_SCHEDULE_TICK: "handle_tick",
}


def test_bench_topic_route_dict_lookup(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark dict-based topic routing (O(1) handler dispatch)."""
    topic = Topics.JOB_LISTING_CREATED
    benchmark(lambda: _TOPIC_TO_HANDLER.get(topic))


def test_bench_topic_route_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark dict-based routing for unregistered topic."""
    benchmark(lambda: _TOPIC_TO_HANDLER.get("unknown.topic.v1"))


def test_bench_topic_startswith_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark topic prefix check (domain filtering)."""
    topic = Topics.JOB_LISTING_CREATED
    benchmark(lambda: topic.startswith("job-listing."))


def test_bench_topic_classify(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark topic classification by extracting components."""
    topic = Topics.JOB_LISTING_CREATED

    def classify() -> tuple[str, str, str]:
        parts = topic.split(".")
        return parts[0], parts[1], parts[2]

    benchmark(classify)


# DLQ routing decision (every error path)


class _RetryStrategy(StrEnum):
    NO_RETRY = "no_retry"
    RETRY_IMMEDIATE = "retry_immediate"
    RETRY_LINEAR = "retry_linear"
    RETRY_EXPONENTIAL = "retry_exponential"


@dataclass(frozen=True, slots=True)
class _ErrorClassification:
    strategy: _RetryStrategy
    max_retries: int
    is_dlq: bool


_CLASSIFICATION_MAP: dict[str, _ErrorClassification] = {
    "DataNotFoundError": _ErrorClassification(_RetryStrategy.NO_RETRY, 0, is_dlq=True),
    "ValidationError": _ErrorClassification(_RetryStrategy.NO_RETRY, 0, is_dlq=True),
    "DataNotAvailableError": _ErrorClassification(_RetryStrategy.RETRY_EXPONENTIAL, 3, is_dlq=False),
    "ExternalServiceError": _ErrorClassification(_RetryStrategy.RETRY_EXPONENTIAL, 3, is_dlq=False),
    "RateLimitedError": _ErrorClassification(_RetryStrategy.RETRY_LINEAR, 5, is_dlq=False),
    "StaleDataError": _ErrorClassification(_RetryStrategy.RETRY_IMMEDIATE, 1, is_dlq=False),
}


def test_bench_dlq_classify_known(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark DLQ classification for a known error type."""
    benchmark(lambda: _CLASSIFICATION_MAP.get("DataNotFoundError"))


def test_bench_dlq_classify_unknown(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark DLQ classification for an unknown error type."""
    benchmark(lambda: _CLASSIFICATION_MAP.get("SomeRandomError"))


def test_bench_dlq_is_retryable_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark checking if an error should be retried."""
    classification = _CLASSIFICATION_MAP["ExternalServiceError"]
    benchmark(lambda: classification.strategy != _RetryStrategy.NO_RETRY)


# Retry backoff computation (every retry decision)

_BASE_BACKOFF_MS = 1000
_MAX_BACKOFF_MS = 30000
_BACKOFF_MULTIPLIER = 2


def _compute_exponential_backoff(attempt: int) -> int:
    """Compute exponential backoff delay in milliseconds."""
    delay = _BASE_BACKOFF_MS * (_BACKOFF_MULTIPLIER**attempt)
    return min(delay, _MAX_BACKOFF_MS)


def _compute_linear_backoff(attempt: int) -> int:
    """Compute linear backoff delay in milliseconds."""
    delay = _BASE_BACKOFF_MS * (attempt + 1)
    return min(delay, _MAX_BACKOFF_MS)


def test_bench_exponential_backoff_first(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark exponential backoff computation (first attempt)."""
    benchmark(_compute_exponential_backoff, 0)


def test_bench_exponential_backoff_third(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark exponential backoff computation (third attempt)."""
    benchmark(_compute_exponential_backoff, 2)


def test_bench_linear_backoff(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark linear backoff computation."""
    benchmark(_compute_linear_backoff, 3)


# Consumer offset tracking simulation (per-partition state)


_COMMIT_BATCH_SIZE = 100


@dataclass
class _PartitionState:
    """Simulates per-partition consumer state."""

    partition: int
    last_offset: int = 0
    last_commit_time: float = field(default_factory=time.monotonic)
    pending_count: int = 0


def test_bench_partition_state_update(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark updating partition state after processing a message."""
    state = _PartitionState(partition=0)

    def update() -> None:
        state.last_offset += 1
        state.pending_count += 1
        if state.pending_count >= _COMMIT_BATCH_SIZE:
            state.last_commit_time = time.monotonic()
            state.pending_count = 0

    benchmark(update)


_PARTITION_STATES: dict[int, _PartitionState] = {
    i: _PartitionState(partition=i, last_offset=i * 1000) for i in range(12)
}


def test_bench_partition_lookup(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark partition state lookup (12 partitions, typical Kafka setup)."""
    benchmark(lambda: _PARTITION_STATES.get(7))

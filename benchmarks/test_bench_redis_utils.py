"""Benchmarks for Redis utility operations (nohiki-redis-utils).

Measures cache key construction, hash computation, value sanitization,
rate limit configuration, and circuit breaker state machine -- all pure
Python operations that don't require a running Redis instance.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import pytest
from nohiki_redis_utils.helpers import hash_dict, make_cache_key, sanitize_cache_value
from nohiki_redis_utils.rate_limit_config import (
    RateLimit,
    TimeUnit,
    per_day,
    per_hour,
    per_minute,
    per_second,
)

# Cache key construction (every cache read/write path)

_SAMPLE_UUID = UUID("550e8400-e29b-41d4-a716-446655440000")


def test_bench_make_cache_key_simple(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark simple cache key from string parts."""
    benchmark(make_cache_key, "listing", "550e8400-e29b-41d4-a716-446655440000")


def test_bench_make_cache_key_uuid(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark cache key with UUID object (requires str conversion)."""
    benchmark(make_cache_key, "listing", _SAMPLE_UUID)


def test_bench_make_cache_key_complex(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark complex cache key with kwargs (typical pattern)."""
    benchmark(
        make_cache_key,
        "correlation",
        "pref-12345",
        version="v1",
        stage="l2r",
        batch_size=150,
    )


# Hash computation (cache invalidation, content hashing)

_SMALL_DICT: dict[str, object] = {
    "skill_id": "python",
    "proficiency": 4,
    "source": "resume",
}
_LARGE_DICT: dict[str, object] = {f"field_{i}": f"value_{i}" for i in range(50)}


def test_bench_hash_dict_small(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark hashing a small dict (3 fields, typical cache key)."""
    benchmark(hash_dict, _SMALL_DICT)


def test_bench_hash_dict_large(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark hashing a large dict (50 fields, content hash)."""
    benchmark(hash_dict, _LARGE_DICT)


def test_bench_sha256_raw(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark raw SHA256 for comparison (lower bound for hash_dict)."""
    data = json.dumps(_SMALL_DICT, sort_keys=True).encode()
    benchmark(lambda: hashlib.sha256(data).hexdigest())


# Value sanitization (every cache write)

_NESTED_VALUE: dict[str, object] = {
    "listing_id": _SAMPLE_UUID,
    "scores": [0.85, 0.92, 0.78],
    "metadata": {"source": "scraper", "version": 3},
    "tags": ["remote", "senior", "python"],
}


def test_bench_sanitize_primitive(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark sanitizing a primitive value (fast path)."""
    benchmark(sanitize_cache_value, "hello")


def test_bench_sanitize_uuid(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark sanitizing a UUID (str conversion)."""
    benchmark(sanitize_cache_value, _SAMPLE_UUID)


def test_bench_sanitize_nested(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark sanitizing a nested dict with mixed types."""
    benchmark(sanitize_cache_value, _NESTED_VALUE)


# Rate limit configuration (constructed once at service startup)


def test_bench_rate_limit_construction(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark RateLimit dataclass construction."""
    benchmark(RateLimit, requests=100, unit=TimeUnit.MINUTES)


def test_bench_rate_limit_window_seconds(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark window_seconds property (used for Redis TTL)."""
    rl = RateLimit(requests=100, unit=TimeUnit.MINUTES)
    benchmark(lambda: rl.window_seconds)


def test_bench_rate_limit_display_name(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark display_name property (used in error messages)."""
    rl = RateLimit(requests=100, unit=TimeUnit.MINUTES)
    benchmark(lambda: rl.display_name)


def test_bench_per_second_factory(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark per_second() convenience factory."""
    benchmark(per_second, 10)


def test_bench_per_minute_factory(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark per_minute() convenience factory."""
    benchmark(per_minute, 100)


def test_bench_per_hour_factory(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark per_hour() convenience factory."""
    benchmark(per_hour, 1000)


def test_bench_per_day_factory(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark per_day() convenience factory."""
    benchmark(per_day, 10000, count=30)


# Circuit breaker state machine (inlined -- Kafka CB uses sync, Redis CB async)

_CB_FAILURE_THRESHOLD = 5
_CB_RECOVERY_TIMEOUT = 30.0


class _CBState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _InlineCB:
    """Inlined Kafka-style circuit breaker for pure state machine benchmarking."""

    failure_threshold: int = _CB_FAILURE_THRESHOLD
    recovery_timeout: float = _CB_RECOVERY_TIMEOUT
    failure_count: int = 0
    last_failure_time: float = 0.0
    state: _CBState = _CBState.CLOSED

    def check_state(self) -> bool:
        """Check if call is allowed, transitioning OPEN→HALF_OPEN if timeout elapsed."""
        if self.state != _CBState.OPEN:
            return True
        if time.monotonic() - self.last_failure_time > self.recovery_timeout:
            self.state = _CBState.HALF_OPEN
            return True
        return False

    def record_failure(self) -> None:
        """Record failure and open circuit if threshold reached."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = _CBState.OPEN

    def record_success(self) -> None:
        """Close circuit on success during HALF_OPEN."""
        if self.state == _CBState.HALF_OPEN:
            self.failure_count = 0
            self.state = _CBState.CLOSED


def test_bench_cb_check_state_closed(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark circuit breaker state check (closed -- fast path)."""
    cb = _InlineCB()
    benchmark(cb.check_state)


def test_bench_cb_check_state_open(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark circuit breaker state check (open -- timeout not elapsed)."""
    cb = _InlineCB(state=_CBState.OPEN, last_failure_time=time.monotonic())
    benchmark(cb.check_state)


def test_bench_cb_record_failure(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark recording a failure (below threshold)."""
    cb = _InlineCB()

    def fail_and_reset() -> None:
        cb.record_failure()
        cb.failure_count = 0
        cb.state = _CBState.CLOSED

    benchmark(fail_and_reset)


def test_bench_cb_record_success_half_open(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark recording success in half-open (closes circuit)."""
    cb = _InlineCB(state=_CBState.HALF_OPEN)

    def succeed_and_reset() -> None:
        cb.record_success()
        cb.state = _CBState.HALF_OPEN

    benchmark(succeed_and_reset)


def test_bench_cb_full_failure_cycle(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full failure cycle: 5 failures → open → check → half-open."""
    cb = _InlineCB()

    def cycle() -> _CBState:
        cb.state = _CBState.CLOSED
        cb.failure_count = 0
        for _ in range(_CB_FAILURE_THRESHOLD):
            cb.record_failure()
        cb.last_failure_time = time.monotonic() - cb.recovery_timeout - 1
        cb.check_state()
        return cb.state

    benchmark(cycle)

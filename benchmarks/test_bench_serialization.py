"""Benchmarks for betterproto2 serialization/deserialization.

Every Kafka event passes through bytes(message) and message_type().parse(raw).
With large ECST snapshots (ListingSnapshot, SearchPrefSnapshot), this is
a throughput-critical path. These benchmarks measure real serialization cost.
"""

from __future__ import annotations

import pytest
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.user.pref.v1 import PrefCreated
from nohiki_test_utils.sample_data import (
    BACKEND_ENGINEER_PREF,
    LISTING_CREATED_SENIOR_PYTHON,
    PREF_CREATED_BACKEND_ENGINEER,
    SENIOR_PYTHON_REMOTE,
)

# Serialization benchmarks (bytes(message))


def test_bench_serialize_listing_snapshot(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ListingSnapshot serialization to bytes."""
    benchmark(bytes, SENIOR_PYTHON_REMOTE)


def test_bench_serialize_listing_created(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full ListingCreated event serialization."""
    benchmark(bytes, LISTING_CREATED_SENIOR_PYTHON)


def test_bench_serialize_search_pref_snapshot(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark SearchPrefSnapshot serialization."""
    benchmark(bytes, BACKEND_ENGINEER_PREF)


def test_bench_serialize_pref_created(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full PrefCreated event serialization."""
    benchmark(bytes, PREF_CREATED_BACKEND_ENGINEER)


def test_bench_serialize_event_metadata(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark EventMetadata serialization (common to all events)."""
    benchmark(bytes, LISTING_CREATED_SENIOR_PYTHON.metadata)


# Deserialization benchmarks (MessageType().parse(raw_bytes))


def test_bench_deserialize_listing_snapshot(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark ListingSnapshot deserialization from bytes."""
    raw = bytes(SENIOR_PYTHON_REMOTE)
    benchmark(lambda: ListingSnapshot().parse(raw))


def test_bench_deserialize_listing_created(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full ListingCreated event deserialization."""
    raw = bytes(LISTING_CREATED_SENIOR_PYTHON)
    benchmark(lambda: ListingCreated().parse(raw))


def test_bench_deserialize_pref_created(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PrefCreated event deserialization."""
    raw = bytes(PREF_CREATED_BACKEND_ENGINEER)
    benchmark(lambda: PrefCreated().parse(raw))


# Round-trip benchmarks (serialize + deserialize)


def test_bench_roundtrip_listing_created(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full serialize + deserialize round-trip for ListingCreated."""

    def roundtrip() -> ListingCreated:
        raw = bytes(LISTING_CREATED_SENIOR_PYTHON)
        return ListingCreated().parse(raw)

    benchmark(roundtrip)


def test_bench_roundtrip_pref_created(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full serialize + deserialize round-trip for PrefCreated."""

    def roundtrip() -> PrefCreated:
        raw = bytes(PREF_CREATED_BACKEND_ENGINEER)
        return PrefCreated().parse(raw)

    benchmark(roundtrip)

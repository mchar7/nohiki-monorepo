"""Benchmarks for Kafka client serialization/deserialization pipeline.

Every Kafka publish goes through bytes(message) and every consume through
MessageType().parse(raw). This file benchmarks the full Kafka client
serialize path, topic resolution, and message routing overhead.
"""

from __future__ import annotations

from typing import Final

import pytest
from nohiki.common.v1 import ListingReference, ListingStatus
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.user.pref.v1 import PrefCreated
from nohiki_test_utils.sample_data import (
    BACKEND_ENGINEER_PREF,
    PREF_CREATED_BACKEND_ENGINEER,
    STAFF_PLATFORM_HYBRID,
    copy_with,
)
from nohiki_test_utils.sample_data._common import make_event_metadata
from nohiki_test_utils.sample_data._ids import EVENT_SENIOR_PYTHON_LISTING_CREATED_ID

# Module-level constants: persona-based realistic worst-case payloads

_LARGE_DESCRIPTION: Final[str] = STAFF_PLATFORM_HYBRID.description * 5
_LARGE_LISTING_SNAPSHOT: Final[ListingSnapshot] = copy_with(STAFF_PLATFORM_HYBRID, description=_LARGE_DESCRIPTION)
_LISTING_CREATED_LARGE: Final[ListingCreated] = ListingCreated(
    metadata=make_event_metadata(
        event_id=EVENT_SENIOR_PYTHON_LISTING_CREATED_ID,
        source_service="job-storage-service",
        correlation_id=EVENT_SENIOR_PYTHON_LISTING_CREATED_ID,
    ),
    listing=ListingReference(listing_id=_LARGE_LISTING_SNAPSHOT.id),
    was_updated=False,
    listing_status=ListingStatus.ACTIVE,
    store_metadata={},
    listing_snapshot=_LARGE_LISTING_SNAPSHOT,
)


# AutoKafkaClient.serialize() equivalent (bytes(message))


def test_bench_kafka_serialize_large_listing(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark Kafka serialize: large ListingCreated (~5KB+ payload)."""
    benchmark(bytes, _LISTING_CREATED_LARGE)


def test_bench_kafka_serialize_multi_location_pref(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark Kafka serialize: multi-location SearchPrefSnapshot."""
    benchmark(bytes, BACKEND_ENGINEER_PREF)


# Consumer deserialization pipeline (parse from raw bytes)


def test_bench_kafka_deserialize_large_listing(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark Kafka deserialize: large ListingCreated from bytes."""
    raw = bytes(_LISTING_CREATED_LARGE)
    benchmark(lambda: ListingCreated().parse(raw))


def test_bench_kafka_deserialize_multi_location_pref(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark Kafka deserialize: multi-location PrefCreated from bytes."""
    raw = bytes(PREF_CREATED_BACKEND_ENGINEER)
    benchmark(lambda: PrefCreated().parse(raw))


# betterproto2 overhead measurements


def test_bench_proto_message_construction(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark constructing a ListingSnapshot via copy_with (no serialization)."""
    benchmark(lambda: copy_with(STAFF_PLATFORM_HYBRID, description=_LARGE_DESCRIPTION))


def test_bench_proto_field_access_pattern(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark typical field access pattern on deserialized message."""
    raw = bytes(_LISTING_CREATED_LARGE)
    msg = ListingCreated().parse(raw)

    def access_fields() -> tuple[str, str, str, int]:
        snap = msg.listing_snapshot
        return (
            snap.title,
            snap.company_name,
            snap.location.city,
            snap.seniority_level,
        )

    benchmark(access_fields)


def test_bench_proto_message_size_calculation(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark calculating serialized message size (len(bytes(msg)))."""

    def size() -> int:
        return len(bytes(_LISTING_CREATED_LARGE))

    benchmark(size)


# Round-trip with large payloads


def test_bench_roundtrip_large_listing(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full round-trip for large ListingCreated (~5KB)."""

    def roundtrip() -> ListingCreated:
        raw = bytes(_LISTING_CREATED_LARGE)
        return ListingCreated().parse(raw)

    benchmark(roundtrip)


def test_bench_roundtrip_repeated_10x(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark 10 consecutive round-trips (simulate burst processing)."""

    def burst() -> list[ListingCreated]:
        results = []
        for _ in range(10):
            raw = bytes(_LISTING_CREATED_LARGE)
            results.append(ListingCreated().parse(raw))
        return results

    benchmark(burst)

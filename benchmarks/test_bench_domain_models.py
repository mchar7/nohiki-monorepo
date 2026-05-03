"""Benchmarks for domain model utilities (nohiki-domain-models).

Measures enum parsing/validation, Pydantic adapter construction,
topic routing, and event metadata creation -- all hot-path operations
in every Kafka handler.
"""

from __future__ import annotations

import pytest
from nohiki.common.v1 import CountryCode, SeniorityLevel
from nohiki_domain_utils.enum_adapter import (
    create_enum_json_schema,
    create_enum_serializer,
    create_enum_validator,
    parse_enum_string,
)
from nohiki_kafka_client.event_metadata import create_event_metadata
from nohiki_kafka_client.topics import Topics

# Enum parsing (every inbound event deserialization)


def test_bench_parse_enum_exact(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark exact enum name parse (fast path)."""
    benchmark(parse_enum_string, CountryCode, "USA")


def test_bench_parse_enum_lowercase(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark case-insensitive enum parse (normalization path)."""
    benchmark(parse_enum_string, CountryCode, "usa")


def test_bench_parse_enum_hyphenated(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark hyphenated string normalization."""
    benchmark(parse_enum_string, SeniorityLevel, "senior")


# Enum validator/serializer creation (once per Pydantic model)


def test_bench_create_enum_validator(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a validator function for betterproto enum."""
    benchmark(create_enum_validator, CountryCode)


def test_bench_enum_validator_call(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark calling the validator (every field validation)."""
    validator = create_enum_validator(CountryCode)
    benchmark(validator, "USA")


def test_bench_create_enum_serializer(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a serializer function for betterproto enum."""
    benchmark(create_enum_serializer, CountryCode)


def test_bench_enum_serializer_call(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark calling the serializer (every response serialization)."""
    serializer = create_enum_serializer(CountryCode)
    benchmark(serializer, CountryCode.USA)


def test_bench_create_enum_json_schema(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark JSON schema generation for OpenAPI (once at startup)."""
    benchmark(create_enum_json_schema, CountryCode)


def test_bench_create_enum_json_schema_with_filter(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark JSON schema with UNSPECIFIED filtering."""
    benchmark(create_enum_json_schema, SeniorityLevel, exclude_unspecified=True)


# Topic constant access (every Kafka publish/subscribe)


def test_bench_topic_access(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark accessing a topic constant (class attribute)."""
    benchmark(lambda: Topics.JOB_LISTING_CREATED)


def test_bench_topic_comparison(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark topic string comparison (routing decision)."""
    topic = "job-listing.cdc.listing-created.v1"
    benchmark(lambda: topic == Topics.JOB_LISTING_CREATED)


# Event metadata creation (every Kafka event published)


def test_bench_create_event_metadata(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating EventMetadata (UUID7 + timestamp + fields)."""
    benchmark(
        create_event_metadata,
        source_service="job-correlation-evaluation-service",
        correlation_id="550e8400-e29b-41d4-a716-446655440000",
    )


def test_bench_create_event_metadata_with_causation(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark creating EventMetadata with causation chain."""
    benchmark(
        create_event_metadata,
        source_service="job-correlation-evaluation-service",
        correlation_id="550e8400-e29b-41d4-a716-446655440000",
        causation_id="660e8400-e29b-41d4-a716-446655440000",
    )

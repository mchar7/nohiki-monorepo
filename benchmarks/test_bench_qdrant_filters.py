"""Benchmarks for Qdrant filter construction (nohiki-qdrant-client).

Measures filter building operations used in every vector search query.
These run on every Stage 1 and Stage 2 retrieval call.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nohiki_qdrant_client.filter_builder import build_filter, build_filter_with_should

# Simple filter construction


def test_bench_filter_single_bool(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a single boolean filter."""
    benchmark(build_filter, {"is_active": True})


def test_bench_filter_single_string(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a single string match filter."""
    benchmark(build_filter, {"job_type": "full_time"})


def test_bench_filter_multi_field(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a multi-field filter (typical query)."""
    benchmark(
        build_filter,
        {
            "is_active": True,
            "seniority_level": 3,
            "work_arrangement": "remote",
            "country": "USA",
        },
    )


def test_bench_filter_list_match_any(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a MatchAny filter (company list)."""
    benchmark(
        build_filter,
        {"company": ["Google", "Meta", "Apple", "Amazon", "Microsoft"]},
    )


def test_bench_filter_range(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a range filter (date range)."""
    benchmark(
        build_filter,
        {"posted_at": {"$gte": datetime(2024, 1, 1, tzinfo=UTC).timestamp()}},
    )


def test_bench_filter_complex_range(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building a complex range filter (salary range)."""
    benchmark(
        build_filter,
        {
            "salary_min": {"$gte": 100000},
            "salary_max": {"$lte": 200000},
            "is_active": True,
        },
    )


# Complex filter with must/should/must_not


def test_bench_filter_with_should(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building complex filter with must + should + must_not."""
    benchmark(
        build_filter_with_should,
        must_filters={"is_active": True, "country": "USA"},
        should_filters=[
            {"work_arrangement": "remote"},
            {"work_arrangement": "hybrid"},
        ],
        must_not_filters={"company": "excluded_corp"},
    )


def test_bench_filter_must_only(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark build_filter_with_should with only must conditions."""
    benchmark(
        build_filter_with_should,
        must_filters={
            "is_active": True,
            "seniority_level": 3,
            "country": "USA",
        },
    )


def test_bench_filter_large_should(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark filter with many should conditions (location alternatives)."""
    locations = [
        {"city": city}
        for city in [
            "San Francisco",
            "New York",
            "Seattle",
            "Austin",
            "Denver",
            "Chicago",
            "Boston",
            "Portland",
            "Los Angeles",
            "Miami",
        ]
    ]
    benchmark(
        build_filter_with_should,
        must_filters={"is_active": True},
        should_filters=locations,
    )

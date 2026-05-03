"""Benchmarks for Pydantic settings construction and validation (nohiki-core-settings).

Every service constructs its settings object once at startup. This measures
the cost of Pydantic validation, env parsing, and mixin composition.
"""

from __future__ import annotations

import os

import pytest
from nohiki_core_settings import NohikiBaseSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict

# Test settings classes (mimicking real service settings)


class _MinimalSettings(NohikiBaseSettings):
    """Minimal settings with only required fields."""

    model_config = SettingsConfigDict(
        env_prefix="BENCH_MINIMAL_",
        env_file=None,
        secrets_dir=None,
    )

    service_name: str = "bench-minimal"
    service_name_friendly: str = "Benchmark Minimal"
    service_desc_friendly: str = "Minimal benchmark settings"
    service_version: str = "0.1.0"


class _FullServiceSettings(NohikiBaseSettings):
    """Full service settings simulating a realistic service config."""

    model_config = SettingsConfigDict(
        env_prefix="BENCH_FULL_",
        env_file=None,
        secrets_dir=None,
    )

    service_name: str = "bench-full"
    service_name_friendly: str = "Benchmark Full"
    service_desc_friendly: str = "Full benchmark settings"
    service_version: str = "0.1.0"

    max_batch_size: int = Field(default=150)
    scoring_timeout_seconds: float = Field(default=30.0)
    enable_caching: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600)
    worker_concurrency: int = Field(default=4)
    log_level: str = Field(default="INFO")


# Settings construction benchmarks


def test_bench_minimal_settings_construction(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark constructing minimal NohikiBaseSettings."""
    benchmark(_MinimalSettings)


def test_bench_full_settings_construction(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark constructing full service settings with many fields."""
    benchmark(_FullServiceSettings)


def test_bench_settings_with_env_override(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark settings construction with environment variable overrides."""
    os.environ["BENCH_FULL_MAX_BATCH_SIZE"] = "200"
    os.environ["BENCH_FULL_SCORING_TIMEOUT_SECONDS"] = "60.0"
    os.environ["BENCH_FULL_ENABLE_CACHING"] = "false"

    try:
        benchmark(_FullServiceSettings)
    finally:
        os.environ.pop("BENCH_FULL_MAX_BATCH_SIZE", None)
        os.environ.pop("BENCH_FULL_SCORING_TIMEOUT_SECONDS", None)
        os.environ.pop("BENCH_FULL_ENABLE_CACHING", None)


def test_bench_settings_init_kwargs(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark settings construction with init kwargs (test pattern)."""
    benchmark(
        _FullServiceSettings,
        max_batch_size=200,
        scoring_timeout_seconds=60.0,
        enable_caching=False,
    )


# Field validation benchmarks


def test_bench_settings_port_validation(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark Pydantic port field validation (ge=1, le=65535)."""
    benchmark(_MinimalSettings, port=8080)


def test_bench_settings_field_access(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark accessing settings fields after construction."""
    settings = _FullServiceSettings()

    def access_all() -> tuple[str, int, float, bool, int, int, str]:
        return (
            settings.service_name,
            settings.max_batch_size,
            settings.scoring_timeout_seconds,
            settings.enable_caching,
            settings.cache_ttl_seconds,
            settings.worker_concurrency,
            settings.log_level,
        )

    benchmark(access_all)


def test_bench_settings_model_dump(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark serializing settings to dict (used for logging config)."""
    settings = _FullServiceSettings()
    benchmark(settings.model_dump)

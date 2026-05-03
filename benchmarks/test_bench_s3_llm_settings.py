"""Benchmarks for S3 and LLM settings/exceptions (nohiki-s3-client, nohiki-llm-client).

Measures Pydantic settings construction, property access, exception
creation, and model fallback mapping -- operations at service startup
and every error path.
"""

from __future__ import annotations

from typing import Final

import pytest
from nohiki_llm_client.constants import (
    DEFAULT_FALLBACK_MODEL,
    OPENROUTER_TO_OPENAI_MODEL_MAP,
)
from nohiki_llm_client.exceptions import (
    LLMAuthenticationError,
    LLMCircuitOpenError,
    LLMContextTooLongError,
    LLMError,
    LLMInvalidSchemaError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMTransientError,
)
from nohiki_llm_client.settings import (
    LLMCachingSettings,
    LLMProviderSettings,
    LLMSettings,
    PhoenixSettings,
)
from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3Error,
    S3ObjectNotFoundError,
    S3PermissionError,
)
from nohiki_s3_client.settings import S3Settings
from pydantic import SecretStr

# S3 Settings construction (once at service startup)


def test_bench_s3_settings_minimal(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark S3Settings with minimal required fields."""
    benchmark(S3Settings, bucket="nohiki-documents")


def test_bench_s3_settings_full(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark S3Settings with all fields populated."""
    benchmark(
        S3Settings,
        endpoint="http://minio:9000",
        access_key=SecretStr("minioadmin"),
        secret_key=SecretStr("minioadmin"),
        region="us-east-1",
        bucket="nohiki-documents",
        connect_timeout=5,
        read_timeout=15,
        use_ssl=False,
    )


# S3 Exceptions (every S3 error path)


def test_bench_s3_not_found(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark S3ObjectNotFoundError creation."""
    benchmark(S3ObjectNotFoundError, "listings/2024/01/abc123.json")


def test_bench_s3_permission(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark S3PermissionError creation."""
    benchmark(S3PermissionError, "templates/private/secret.html")


def test_bench_s3_connection(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark S3ConnectionError creation."""
    benchmark(S3ConnectionError, "Connection refused: minio:9000")


def test_bench_s3_error_key_access(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark accessing .key attribute on S3 exception."""
    err = S3ObjectNotFoundError("listings/abc.json")
    benchmark(lambda: err.key)


def test_bench_s3_isinstance_check(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark isinstance check for S3 error hierarchy."""
    err = S3ObjectNotFoundError("listings/abc.json")
    benchmark(lambda: isinstance(err, S3Error))


# LLM Provider Settings (once at service startup)


def test_bench_llm_provider_default(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMProviderSettings with defaults."""
    benchmark(LLMProviderSettings)


def test_bench_llm_provider_full(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMProviderSettings with all fields."""
    benchmark(
        LLMProviderSettings,
        openrouter_api_key=SecretStr("sk-or-test-key"),
        default_model="anthropic/claude-sonnet-4",
        timeout_seconds=120.0,
        max_retries=3,
        temperature=0.0,
        max_tokens=4096,
        reasoning_effort="medium",
    )


def test_bench_llm_settings_full(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark full LLMSettings with all sub-models."""
    benchmark(LLMSettings)


def test_bench_llm_caching_settings(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMCachingSettings construction."""
    benchmark(LLMCachingSettings)


def test_bench_phoenix_settings(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PhoenixSettings construction."""
    benchmark(PhoenixSettings)


def test_bench_llm_active_provider(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark active_provider property resolution."""
    settings = LLMProviderSettings(openrouter_api_key=SecretStr("sk-or-test"))
    benchmark(lambda: settings.active_provider)


def test_bench_llm_active_api_key(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark active_api_key property (SecretStr.get_secret_value)."""
    settings = LLMProviderSettings(openrouter_api_key=SecretStr("sk-or-test"))
    benchmark(lambda: settings.active_api_key)


# LLM Model fallback mapping (provider failover)

_MODEL_LOOKUP: Final[str] = "google/gemini-3-flash-preview"


def test_bench_model_map_hit(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark OpenRouter→OpenAI model fallback lookup (hit)."""
    benchmark(lambda: OPENROUTER_TO_OPENAI_MODEL_MAP.get(_MODEL_LOOKUP, DEFAULT_FALLBACK_MODEL))


def test_bench_model_map_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark OpenRouter→OpenAI model fallback lookup (miss, default)."""
    benchmark(lambda: OPENROUTER_TO_OPENAI_MODEL_MAP.get("unknown/model", DEFAULT_FALLBACK_MODEL))


# LLM Exceptions (every LLM error path)


def test_bench_llm_rate_limit(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMRateLimitError creation."""
    benchmark(LLMRateLimitError, "Rate limit exceeded", retry_after=60)


def test_bench_llm_timeout(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMTimeoutError creation."""
    benchmark(LLMTimeoutError, "Request timed out after 120s")


def test_bench_llm_circuit_open(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMCircuitOpenError creation."""
    benchmark(LLMCircuitOpenError, "Circuit breaker open")


def test_bench_llm_context_too_long(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMContextTooLongError creation."""
    benchmark(LLMContextTooLongError, "Input exceeds 128k tokens")


def test_bench_llm_auth_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMAuthenticationError creation."""
    benchmark(LLMAuthenticationError, "Invalid API key")


def test_bench_llm_schema_error(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark LLMInvalidSchemaError creation."""
    benchmark(LLMInvalidSchemaError, "Cannot process output model")


def test_bench_llm_isinstance_transient(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark isinstance check for transient vs permanent LLM errors."""
    err = LLMRateLimitError("Rate limit", retry_after=30)
    benchmark(lambda: isinstance(err, LLMTransientError))


def test_bench_llm_isinstance_base(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark isinstance check against base LLMError."""
    err = LLMContextTooLongError("Too long")
    benchmark(lambda: isinstance(err, LLMError))


def test_bench_llm_retry_after_access(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark accessing retry_after on rate limit error."""
    err = LLMRateLimitError("Rate limit", retry_after=60)
    benchmark(lambda: err.retry_after)

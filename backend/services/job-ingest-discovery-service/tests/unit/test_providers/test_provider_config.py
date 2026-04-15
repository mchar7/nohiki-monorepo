from __future__ import annotations

from job_ingest_discovery_service.providers.config import (
    FallbackConfig,
    FallbackTrigger,
    ProviderConfig,
    ProviderRegistryConfig,
)


def test_fallback_trigger_values() -> None:
    assert FallbackTrigger.RATE_LIMIT_EXCEEDED.value == "rate_limit_exceeded"
    assert FallbackTrigger.ERROR.value == "error"
    assert FallbackTrigger.TIMEOUT.value == "timeout"


def test_config_defaults() -> None:
    fallback = FallbackConfig()
    assert fallback.enabled is False
    assert fallback.rate_limit_wait_threshold_seconds == 1800
    assert fallback.error_duration_threshold_seconds == 300
    assert fallback.min_consecutive_errors == 3

    provider = ProviderConfig(name="jobspy")
    assert provider.enabled is True
    assert provider.priority == 100
    assert provider.sources == []
    assert provider.fallback.enabled is False

    registry = ProviderRegistryConfig()
    assert registry.providers == []
    assert registry.allow_multiple_per_source is True

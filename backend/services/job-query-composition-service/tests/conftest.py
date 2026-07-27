"""Test configuration and fixtures for job-query-composition-service."""

from __future__ import annotations

import os

os.environ["JOB_QUERY_COMPOSITION_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["JOB_QUERY_COMPOSITION_DATABASE__SCHEMA_NAME"] = "job_query_composition_schema"
os.environ["JOB_QUERY_COMPOSITION_KAFKA__DSN"] = "kafka://localhost:29092"

# Disable OpenTelemetry and set test mode BEFORE any imports
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_LOGS_EXPORTER"] = "none"
os.environ["TEST_MODE"] = "true"
os.environ["TESTING"] = "true"

# Required settings for pydantic-settings validation
os.environ.setdefault(
    "JOB_QUERY_COMPOSITION_DATABASE__DSN",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault("JOB_QUERY_COMPOSITION_REDIS__DSN", "redis://localhost:6379/0")
os.environ.setdefault("JOB_QUERY_COMPOSITION_KAFKA__DSN", "kafka://localhost:29092")
os.environ.setdefault("JOB_QUERY_COMPOSITION_KAFKA__CONSUMER_GROUP", "test-consumer-group")
os.environ.setdefault("ENVIRONMENT", "development")

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from job_query_composition_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

"""Test configuration and fixtures for job-ingest-schedule-service."""

from __future__ import annotations

import os

os.environ["JOB_INGEST_SCHEDULE_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["JOB_INGEST_SCHEDULE_DATABASE__SCHEMA_NAME"] = "job_ingest_schedule_schema"
os.environ["JOB_INGEST_SCHEDULE_KAFKA__DSN"] = "kafka://localhost:29092"

# Disable OpenTelemetry completely during tests BEFORE any imports
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_LOGS_EXPORTER"] = "none"
os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"
os.environ["TEST_MODE"] = "true"
os.environ["TESTING"] = "true"

# Required settings for pydantic-settings validation (with service env prefix)
os.environ.setdefault(
    "JOB_INGEST_SCHEDULE_DATABASE__DSN",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault("JOB_INGEST_SCHEDULE_KAFKA__DSN", "kafka://localhost:29092")
os.environ.setdefault("JOB_INGEST_SCHEDULE_KAFKA__CONSUMER_GROUP", "test-consumer-group")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Reset settings cache between tests."""
    from job_ingest_schedule_service.core.config import get_settings

    get_settings.cache_clear()

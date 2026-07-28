"""Test configuration and fixtures for job-storage-service."""

from __future__ import annotations

import os

os.environ["JOB_STORAGE_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["JOB_STORAGE_DATABASE__SCHEMA_NAME"] = "job_storage_schema"
os.environ["JOB_STORAGE_KAFKA__DSN"] = "kafka://localhost:29092"

# Disable OpenTelemetry and set test mode BEFORE any imports
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_LOGS_EXPORTER"] = "none"
os.environ["TEST_MODE"] = "true"
os.environ["TESTING"] = "true"

# Required settings for pydantic-settings validation
os.environ.setdefault("JOB_STORAGE_DATABASE__DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JOB_STORAGE_REDIS__DSN", "redis://localhost:6379/0")
os.environ.setdefault("JOB_STORAGE_KAFKA__DSN", "kafka://localhost:29092")
os.environ.setdefault("JOB_STORAGE_KAFKA__CONSUMER_GROUP", "test-consumer-group")
os.environ.setdefault("ENVIRONMENT", "development")

from collections.abc import Generator

import pytest
from nohiki_db_utils.testing import (
    async_engine,
    async_session,
    async_session_factory,
    postgres_container,
)
from nohiki_test_utils import setup_test_secrets

__all__ = [
    "async_engine",
    "async_session",
    "async_session_factory",
    "postgres_container",
    "setup_test_secrets",
]


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from job_storage_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

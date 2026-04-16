"""Test configuration and fixtures for job-ingest-enrichment-service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from nohiki_test_utils import setup_test_secrets

if TYPE_CHECKING:
    from collections.abc import Generator


def _setup_test_environment() -> None:
    """Set up test environment variables before importing service modules."""
    repo_root = Path(__file__).resolve().parents[4]
    manifest_path = repo_root / "data" / "config" / "semantic_representation_manifest.json"

    os.environ["JOB_INGEST_ENRICHMENT_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
    os.environ["JOB_INGEST_ENRICHMENT_DATABASE__SCHEMA_NAME"] = "job_ingest_enrichment_schema"
    os.environ["JOB_INGEST_ENRICHMENT_KAFKA__DSN"] = "kafka://localhost:29092"
    os.environ["JOB_INGEST_ENRICHMENT_MANIFEST_PATH"] = str(manifest_path)

    # Disable OpenTelemetry completely during tests BEFORE any imports
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["OTEL_TRACES_EXPORTER"] = "none"
    os.environ["OTEL_METRICS_EXPORTER"] = "none"
    os.environ["OTEL_LOGS_EXPORTER"] = "none"
    os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"
    os.environ["TEST_MODE"] = "true"
    os.environ["TESTING"] = "true"

    # Required settings for pydantic-settings validation (with service env prefix)
    os.environ.setdefault("JOB_INGEST_ENRICHMENT_DATABASE__DSN", "postgresql+asyncpg://test:test@localhost:5432/test")
    os.environ.setdefault("JOB_INGEST_ENRICHMENT_REDIS__DSN", "redis://localhost:6379/0")
    os.environ.setdefault("JOB_INGEST_ENRICHMENT_KAFKA__DSN", "kafka://localhost:29092")
    os.environ.setdefault("JOB_INGEST_ENRICHMENT_KAFKA__CONSUMER_GROUP", "test-consumer-group")
    os.environ.setdefault("JOB_INGEST_ENRICHMENT_LLM__PROVIDER__MODELS__0__MODEL", "openrouter:test/model")
    os.environ.setdefault("JOB_INGEST_ENRICHMENT_LLM__PROVIDER__API_KEYS__OPENROUTER", "test-api-key")
    os.environ.setdefault("ENVIRONMENT", "development")


# CRITICAL: Set up environment BEFORE any service module imports
_setup_test_environment()

__all__ = [
    "setup_test_secrets",
]


@pytest.fixture(autouse=True)
def _reset_caches() -> Generator[None]:
    """Reset configuration caches before and after each test."""
    from job_ingest_enrichment_service.core.config import get_settings
    from nohiki_ml_manifest import ManifestCache

    get_settings.cache_clear()
    ManifestCache.reset()
    yield
    get_settings.cache_clear()
    ManifestCache.reset()

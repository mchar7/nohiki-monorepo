"""Pytest configuration for ml-compute-service tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest


def _setup_test_environment() -> None:
    """Set up test environment variables before importing service modules."""
    # Set up paths
    repo_root = Path(__file__).resolve().parents[4]
    manifest_path = repo_root / "data" / "config" / "semantic_representation_manifest.json"

    os.environ["ML_COMPUTE_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
    os.environ["ML_COMPUTE_DATABASE__SCHEMA_NAME"] = "ml_compute_schema"
    os.environ["ML_COMPUTE_KAFKA__DSN"] = "kafka://localhost:29092"
    os.environ["ML_COMPUTE_MANIFEST_PATH"] = str(manifest_path)

    # Disable OpenTelemetry completely during tests BEFORE any imports
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["OTEL_TRACES_EXPORTER"] = "none"
    os.environ["OTEL_METRICS_EXPORTER"] = "none"
    os.environ["OTEL_LOGS_EXPORTER"] = "none"
    os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"
    os.environ["TEST_MODE"] = "true"

    # Required settings for pydantic-settings validation (with service env prefix)
    os.environ.setdefault("ML_COMPUTE_REDIS__DSN", "redis://localhost:6379/0")
    os.environ.setdefault("ML_COMPUTE_KAFKA__DSN", "kafka://localhost:29092")
    os.environ.setdefault("ML_COMPUTE_KAFKA__CONSUMER_GROUP", "ml-compute-service")
    os.environ.setdefault("ML_COMPUTE_S3__BUCKET", "test-bucket")
    os.environ.setdefault("ML_COMPUTE_S3__REGION", "us-east-1")
    os.environ.setdefault("ML_COMPUTE_S3__ENDPOINT_URL", "http://localhost:9000")
    os.environ.setdefault("ML_COMPUTE_S3__ACCESS_KEY_ID", "test-key")
    os.environ.setdefault("ML_COMPUTE_S3__SECRET_ACCESS_KEY", "test-secret")
    os.environ.setdefault("ENVIRONMENT", "development")


# CRITICAL: Set up environment BEFORE any service module imports
_setup_test_environment()

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _reset_caches() -> Generator[None]:
    """Reset configuration caches before and after each test."""
    from ml_compute_service.core.config import get_settings
    from nohiki_ml_manifest import ManifestCache

    get_settings.cache_clear()
    ManifestCache.reset()
    yield
    get_settings.cache_clear()
    ManifestCache.reset()

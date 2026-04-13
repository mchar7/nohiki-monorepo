"""Test configuration and fixtures for job-correlation-evaluation-service."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from nohiki_ml_manifest.testing import get_test_manifest_path
from nohiki_test_utils import get_repo_root, setup_test_secrets, valid_internal_token


def _setup_test_environment() -> None:
    """Set up test environment variables before importing service modules."""
    os.environ["TEST_MODE"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["TESTING"] = "true"

    os.environ.setdefault(
        "JOB_CORRELATION_EVAL_DATABASE__DSN",
        "postgresql://test:test@localhost:5432/test",
    )
    os.environ.setdefault(
        "JOB_CORRELATION_EVAL_DATABASE__SCHEMA_NAME",
        "job_correlation_schema",
    )
    os.environ.setdefault(
        "JOB_CORRELATION_EVAL_KAFKA__BOOTSTRAP_SERVERS",
        "localhost:29092",
    )
    os.environ.setdefault("JOB_CORRELATION_EVAL_S3__ENDPOINT", "http://localhost:9000")
    os.environ.setdefault("JOB_CORRELATION_EVAL_S3__ACCESS_KEY", "test")
    os.environ.setdefault("JOB_CORRELATION_EVAL_S3__SECRET_KEY", "test")
    os.environ.setdefault("JOB_CORRELATION_EVAL_S3__BUCKET", "test-bucket")
    os.environ.setdefault("JOB_CORRELATION_EVAL_LLM__PROVIDER__MODELS__0__MODEL", "openrouter:test/model")
    os.environ.setdefault("JOB_CORRELATION_EVAL_LLM__PROVIDER__API_KEYS__OPENROUTER", "test-api-key")
    os.environ.setdefault("JOB_CORRELATION_EVAL_REDIS__DSN", "redis://localhost:6379/0")

    os.environ.setdefault("JOB_CORRELATION_EVAL_MANIFEST_PATH", str(get_test_manifest_path()))

    # L2R model paths point at canonical 32-feature artifacts; tests load
    # the model file shipped at models/l2r/.
    repo_root = get_repo_root()
    models_dir = repo_root / "models" / "l2r"
    os.environ.setdefault("JOB_CORRELATION_EVAL_ML__L2R__MODEL_PATH", str(models_dir / "l2r_lightgbm.txt"))
    os.environ.setdefault("JOB_CORRELATION_EVAL_ML__L2R__CALIBRATOR_PATH", str(models_dir / "calibrator.joblib"))
    os.environ.setdefault("JOB_CORRELATION_EVAL_ML__L2R__EXPECTED_FEATURE_COUNT", "32")


# CRITICAL: Set up environment BEFORE any service module imports
_setup_test_environment()


def _get_app() -> FastAPI:
    """Import and return app after environment setup."""
    from job_correlation_evaluation_service.main import app

    return app


def _get_matcher_service_class() -> type:
    """Import and return JobMatcherService class after environment setup."""
    from job_correlation_evaluation_service.services.matcher_service import (
        JobMatcherService,
    )

    return JobMatcherService


__all__ = [
    "setup_test_secrets",
    "valid_internal_token",
]


@pytest.fixture(autouse=True)
def _reset_caches() -> Generator[None]:
    """Reset configuration caches before and after each test."""
    from job_correlation_evaluation_service.core.config import get_settings
    from nohiki_ml_manifest import ManifestCache

    get_settings.cache_clear()
    ManifestCache.reset()
    yield
    get_settings.cache_clear()
    ManifestCache.reset()


@pytest.fixture(autouse=True, scope="session")
def cleanup_kafka_client() -> Generator[None]:
    """Clean up Kafka client after all tests to prevent producer warning.

    The warning "Producer terminating with N messages still in queue"
    occurs when the kafka_client is imported but not properly closed.
    """
    yield

    try:
        from job_correlation_evaluation_service.core.kafka import kafka_client

        # Mark as shutdown to prevent cleanup attempts on closed loop
        kafka_client._shutdown_requested = True

        # Clean up producer directly if it exists, avoiding async close
        if kafka_client._producer is not None:
            kafka_client._producer = None
            kafka_client._producer_ready = False
    except ImportError, RuntimeError:
        # Service module may not be importable in minimal test environments;
        # the producer cleanup is best-effort to silence the librdkafka
        # "Producer terminating with N messages still in queue" warning.
        pass

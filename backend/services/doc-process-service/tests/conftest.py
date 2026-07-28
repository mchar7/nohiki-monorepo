"""Shared fixtures for doc_process_service tests."""

from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import patch

import pytest


def pytest_configure() -> None:
    """Set required environment variables for tests before any imports."""
    os.environ.setdefault("DOC_PROCESS_S3__BUCKET", "test-bucket")
    os.environ.setdefault("DOC_PROCESS_S3__ENDPOINT", "http://localhost:9000")
    os.environ.setdefault("DOC_PROCESS_KAFKA__DSN", "kafka://localhost:29092")
    os.environ.setdefault("DOC_PROCESS_REDIS__DSN", "redis://localhost:6379")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from doc_process_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _initialize_metrics() -> Generator[None]:
    """Initialize DocProcessMetrics singleton for each test."""
    from doc_process_service.metrics import DocProcessMetrics

    previous = DocProcessMetrics._instance
    DocProcessMetrics.initialize()
    yield
    DocProcessMetrics._instance = previous


@pytest.fixture
def _mock_sleep() -> Generator[None]:
    """Mock time.sleep to avoid delays during tests."""
    with patch("time.sleep"):
        yield

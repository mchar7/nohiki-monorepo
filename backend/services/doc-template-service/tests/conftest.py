"""Test fixtures for document generator tests."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

# Import centralized fixtures after TYPE_CHECKING block

# Set required environment variables for Settings (prefix: DOC_TEMPLATE_)
os.environ.setdefault("DOC_TEMPLATE_DATABASE__DSN", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DOC_TEMPLATE_DATABASE__SCHEMA_NAME", "doc_layout_schema")
os.environ.setdefault("DOC_TEMPLATE_KAFKA__BOOTSTRAP_SERVERS", "localhost:29092")
os.environ.setdefault("DOC_TEMPLATE_REDIS__CONNECTION_STRING", "redis://localhost:6379/0")
os.environ.setdefault("DOC_TEMPLATE_S3__ENDPOINT", "http://localhost:9000")
os.environ.setdefault("DOC_TEMPLATE_S3__ACCESS_KEY", "test-access-key")
os.environ.setdefault("DOC_TEMPLATE_S3__SECRET_KEY", "test-secret-key")
os.environ.setdefault("DOC_TEMPLATE_S3__BUCKET", "test-bucket")
os.environ.setdefault("DOC_TEMPLATE_S3__REGION", "us-east-1")
os.environ.setdefault("TEST_MODE", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

# Mock create_cache BEFORE importing service modules to prevent real Redis connections
_mock_cache = AsyncMock()
_mock_cache.get = AsyncMock(return_value=None)
_mock_cache.set = AsyncMock(return_value=None)
_mock_cache.delete = AsyncMock(return_value=None)
_mock_cache.close = AsyncMock(return_value=None)

_create_cache_patcher = patch("nohiki_redis_utils.create_cache", return_value=_mock_cache)
_create_cache_patcher.start()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    """Clean up patchers after test session."""
    _create_cache_patcher.stop()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Reset settings cache between tests."""
    from doc_template_service.core.config import get_settings

    get_settings.cache_clear()

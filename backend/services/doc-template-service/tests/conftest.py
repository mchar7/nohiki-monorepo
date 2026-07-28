"""Test fixtures for document generator tests."""

from __future__ import annotations

import importlib
import os
from collections.abc import Generator
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

# Initialize only the service-local cache singletons with the test cache.
_mock_cache = AsyncMock()
_mock_cache.get = AsyncMock(return_value=None)
_mock_cache.set = AsyncMock(return_value=None)
_mock_cache.delete = AsyncMock(return_value=None)
_mock_cache.close = AsyncMock(return_value=None)

with patch("nohiki_redis_utils.create_cache", return_value=_mock_cache):
    importlib.import_module("doc_template_service.core.generator.cache")
    importlib.import_module("doc_template_service.services.template_service")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from doc_template_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

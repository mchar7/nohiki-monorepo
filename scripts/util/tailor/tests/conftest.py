"""Shared pytest fixtures and configuration for tailor CLI tests.

Env vars must be set before any tailor or doc-template-service imports.
Redis is patched at module level to prevent connection attempts during
import of doc-template-service components.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

# Environment variables -- must be set before importing anything from tailor
# or doc-template-service which validates settings at import time.
os.environ.setdefault("DOC_TEMPLATE_DATABASE__DSN", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("DOC_TEMPLATE_DATABASE__SCHEMA_NAME", "doc_template_schema")
os.environ.setdefault("DOC_TEMPLATE_REDIS__DSN", "redis://localhost:6379/0")
os.environ.setdefault("DOC_TEMPLATE_KAFKA__DSN", "kafka://localhost:29092")
os.environ.setdefault("DOC_TEMPLATE_S3__ENDPOINT", "http://localhost:9000")
os.environ.setdefault("DOC_TEMPLATE_S3__ACCESS_KEY", "dummy")
os.environ.setdefault("DOC_TEMPLATE_S3__SECRET_KEY", "dummy")
os.environ.setdefault("DOC_TEMPLATE_S3__BUCKET", "dummy")
os.environ.setdefault("DOC_TEMPLATE_GOTENBERG__BASE_URL", "http://localhost:3000")
os.environ.setdefault("DOC_TEMPLATE_GOTENBERG__REQUEST_TIMEOUT_S", "30")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

# TailorSettings uses env_prefix="TAILOR_" and env_nested_delimiter="__".
# Top-level fields use TAILOR_<FIELD>, nested use TAILOR_<FIELD>__<NESTED>.
os.environ.setdefault("TAILOR_SERVICE_NAME", "tailor-cli")
os.environ.setdefault("TAILOR_SERVICE_NAME_FRIENDLY", "Nohiki Tailoring CLI")
os.environ.setdefault("TAILOR_SERVICE_DESC_FRIENDLY", "Manual document tailoring tool")
os.environ.setdefault("TAILOR_SERVICE_VERSION", "0.1.0")

# LLM model string -- simple flat field, no nested Pydantic settings required.
os.environ.setdefault("TAILOR_LLM_MODEL", "openrouter:google/gemini-flash-1.5")

# Patch nohiki_redis_utils.create_cache before any service imports trigger it.
# doc-template-service may initialise Redis at import time in some paths.
_mock_cache = AsyncMock()
_mock_cache.get = AsyncMock(return_value=None)
_mock_cache.set = AsyncMock(return_value=None)
_mock_cache.delete = AsyncMock(return_value=None)
_mock_cache.close = AsyncMock(return_value=None)

_create_cache_patcher = patch("nohiki_redis_utils.create_cache", return_value=_mock_cache)
_create_cache_patcher.start()

# Deferred imports (after env vars and patches are in place)

import pytest
from tailor.core.config import get_settings


def pytest_sessionfinish() -> None:
    """Stop the Redis cache patcher when the test session ends."""
    _create_cache_patcher.stop()


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Iterator[None]:
    """Clear the lru_cache on get_settings before each test.

    Prevents cached TailorSettings from leaking state between tests that
    modify environment variables or patch settings-related code.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

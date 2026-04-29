"""Test fixtures for user-pref-service."""

from __future__ import annotations

import os

# Set testing environment BEFORE any imports that might trigger Settings loading
os.environ["TESTING"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["USER_PREF_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["USER_PREF_DATABASE__SCHEMA_NAME"] = "user_pref_schema"
os.environ["USER_PREF_KAFKA__DSN"] = "kafka://localhost:29092"

from collections.abc import Generator

import pytest
from nohiki_ml_manifest.testing import get_test_manifest_path

# Set manifest path using centralized resolution
os.environ["USER_PREF_MANIFEST_PATH"] = str(get_test_manifest_path())


@pytest.fixture(autouse=True)
def _reset_caches() -> Generator[None]:
    """Reset configuration caches before and after each test."""
    from nohiki_ml_manifest import ManifestCache
    from user_pref_service.core.config import get_settings

    get_settings.cache_clear()
    ManifestCache.reset()
    yield
    get_settings.cache_clear()
    ManifestCache.reset()

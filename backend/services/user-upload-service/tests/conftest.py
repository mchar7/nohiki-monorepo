"""Test fixtures for user-upload-service."""

from __future__ import annotations

import os

os.environ["USER_UPLOAD_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["USER_UPLOAD_DATABASE__SCHEMA_NAME"] = "user_upload_schema"
os.environ["USER_UPLOAD_KAFKA__DSN"] = "kafka://localhost:29092"
os.environ["USER_UPLOAD_S3__BUCKET"] = "test-bucket"
import uuid

import pytest

# Set testing environment before any imports
os.environ["TESTING"] = "true"
os.environ["TEST_MODE"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Reset settings cache between tests."""
    from user_upload_service.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def sample_user_id() -> uuid.UUID:
    """Provide a consistent test user ID."""
    return uuid.UUID("12345678-1234-5678-1234-567812345678")

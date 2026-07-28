"""Test fixtures for user-auth-service."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

# Set testing environment before any imports
os.environ["TESTING"] = "true"
os.environ["TEST_MODE"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

# Set required environment variables for Settings validation
# Settings uses USER_AUTH_ prefix with DatabaseMixin and KafkaMixin
os.environ["USER_AUTH_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["USER_AUTH_DATABASE__SCHEMA_NAME"] = "user_auth_schema"
os.environ["USER_AUTH_KAFKA__DSN"] = "kafka://localhost:29092"
os.environ["USER_AUTH_REDIS__DSN"] = "redis://localhost:6379/0"


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from user_auth_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

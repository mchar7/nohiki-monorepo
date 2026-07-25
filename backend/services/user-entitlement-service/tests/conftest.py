"""Test configuration and fixtures for user-entitlement-service."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

# Set testing mode before importing anything else
os.environ["TESTING"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

# Set required environment variables for Settings validation
# Settings uses USER_ENTITLEMENT_ prefix with DatabaseMixin and KafkaMixin
os.environ["USER_ENTITLEMENT_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["USER_ENTITLEMENT_DATABASE__SCHEMA_NAME"] = "user_entitlement_schema"
os.environ["USER_ENTITLEMENT_KAFKA__DSN"] = "kafka://localhost:29092"


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from user_entitlement_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

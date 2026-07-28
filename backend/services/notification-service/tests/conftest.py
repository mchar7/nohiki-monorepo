"""Test configuration and fixtures for notification-service."""

from __future__ import annotations

import os

# Set testing environment BEFORE any imports that might trigger Settings loading
os.environ["TESTING"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["NOTIFICATION_DATABASE__DSN"] = "postgresql://test:test@localhost:5432/test"
os.environ["NOTIFICATION_DATABASE__SCHEMA_NAME"] = "notification_schema"
os.environ["NOTIFICATION_KAFKA__DSN"] = "kafka://localhost:29092"
os.environ["NOTIFICATION_REDIS__DSN"] = "redis://localhost:6379/0"

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final

import pytest
from nohiki.common.v1 import NotificationChannel
from nohiki_observability import get_logger
from nohiki_redis_utils import RateLimiter, RateLimitResult
from nohiki_test_utils import setup_test_secrets
from notification_service.core.providers import (
    BaseProvider,
    ProviderResult,
    clear_provider_registry,
)
from notification_service.db.models import Message
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

logger = get_logger(__name__)


def get_async_db() -> AsyncGenerator[AsyncSession]:
    msg = "get_async_db dependency is not used in notification-service tests"
    raise RuntimeError(msg)


TEST_EMAIL: Final[str] = "test@example.com"
TEST_DOMAIN: Final[str] = "example.com"

__all__ = [
    "setup_test_secrets",
]


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from notification_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class MockRateLimiter(RateLimiter):
    """Mock rate limiter for testing."""

    def __init__(
        self,
        allowed_keys: list[str] | None = None,
        denied_keys: list[str] | None = None,
    ) -> None:
        """Initialize with keys that should be allowed/denied."""
        self.allowed_keys = allowed_keys or []
        self.denied_keys = denied_keys or []
        self.calls: list[str] = []

    async def check(self, key: str) -> RateLimitResult:
        """Record the call and return based on configured keys."""
        self.calls.append(key)

        now = datetime.now(UTC).timestamp()
        if key in self.denied_keys:
            return RateLimitResult(allowed=False, remaining=0, reset_at=now + 60, retry_after=60.0)
        # Default to allowed
        return RateLimitResult(allowed=True, remaining=10, reset_at=now + 60)

    async def reset(self, key: str) -> None:
        """Reset rate limit for key."""


class MockProvider(BaseProvider):
    """Mock provider for testing."""

    channel = NotificationChannel.EMAIL
    name: ClassVar[str] = "mock_provider"
    required_secrets: ClassVar[list[str]] = []

    async def send(self, message: Message) -> ProviderResult:
        """Mock send method."""
        _ = message  # Unused in mock
        return ProviderResult(success=True, provider_msg_id="mock-id")

    async def validate_config(self) -> bool:
        """Mock validate_config method."""
        return True


@pytest.fixture(autouse=True)
def clear_registry() -> Generator[None]:
    """Clear the provider registry before and after each test."""
    clear_provider_registry()
    yield
    clear_provider_registry()

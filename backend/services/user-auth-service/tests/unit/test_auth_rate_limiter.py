"""Unit tests for auth_rate_limiter module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status
from nohiki_redis_utils import AuthRateLimiter as RedisAuthRateLimiter
from nohiki_redis_utils.multi_tier_rate_limiter import MultiTierCheckResult
from user_auth_service.core.config import AuthRateLimitConfig
from user_auth_service.services.auth_rate_limiter import (
    AuthRateLimiterService,
    get_auth_rate_limiter,
    reset_auth_rate_limiter,
)


@pytest.fixture
def mock_redis_limiter() -> MagicMock:
    """Create a mock RedisAuthRateLimiter."""
    return MagicMock(spec=RedisAuthRateLimiter)


@pytest.fixture
def auth_rate_limiter_service(mock_redis_limiter: MagicMock) -> AuthRateLimiterService:
    """Create an AuthRateLimiterService instance with mocked underlying limiter."""
    return AuthRateLimiterService(mock_redis_limiter)


class TestAuthRateLimiterService:
    """Tests for AuthRateLimiterService class."""

    @pytest.mark.asyncio
    async def test_check_login_allowed(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_login when rate limit is not exceeded."""
        mock_redis_limiter.check_login = AsyncMock(
            return_value=MultiTierCheckResult(allowed=True, exceeded_tier=None, retry_after=None)
        )

        await auth_rate_limiter_service.check_login("test@example.com")

        mock_redis_limiter.check_login.assert_awaited_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_check_login_exceeded_with_retry_after(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_login when rate limit is exceeded with retry_after."""
        mock_redis_limiter.check_login = AsyncMock(
            return_value=MultiTierCheckResult(allowed=False, exceeded_tier="minute", retry_after=45.5)
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_rate_limiter_service.check_login("test@example.com")

        assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "45 seconds" in exc_info.value.detail
        assert exc_info.value.headers == {"Retry-After": "45"}

    @pytest.mark.asyncio
    async def test_check_login_exceeded_without_retry_after(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_login when rate limit is exceeded without retry_after."""
        mock_redis_limiter.check_login = AsyncMock(
            return_value=MultiTierCheckResult(allowed=False, exceeded_tier="hour", retry_after=None)
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_rate_limiter_service.check_login("192.168.1.1")

        assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "60 seconds" in exc_info.value.detail
        assert exc_info.value.headers == {"Retry-After": "60"}

    @pytest.mark.asyncio
    async def test_check_register_allowed(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_register when rate limit is not exceeded."""
        mock_redis_limiter.check_register = AsyncMock(
            return_value=MultiTierCheckResult(allowed=True, exceeded_tier=None, retry_after=None)
        )

        await auth_rate_limiter_service.check_register("192.168.1.100")

        mock_redis_limiter.check_register.assert_awaited_once_with("192.168.1.100")

    @pytest.mark.asyncio
    async def test_check_register_exceeded_with_retry_after(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_register when rate limit is exceeded with retry_after."""
        mock_redis_limiter.check_register = AsyncMock(
            return_value=MultiTierCheckResult(allowed=False, exceeded_tier="hour", retry_after=1800.0)
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_rate_limiter_service.check_register("192.168.1.100")

        assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "1800 seconds" in exc_info.value.detail
        assert exc_info.value.headers == {"Retry-After": "1800"}

    @pytest.mark.asyncio
    async def test_check_register_exceeded_without_retry_after(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_register when rate limit is exceeded without retry_after."""
        mock_redis_limiter.check_register = AsyncMock(
            return_value=MultiTierCheckResult(allowed=False, exceeded_tier="day", retry_after=None)
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_rate_limiter_service.check_register("192.168.1.100")

        assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "3600 seconds" in exc_info.value.detail
        assert exc_info.value.headers == {"Retry-After": "3600"}

    @pytest.mark.asyncio
    async def test_check_password_reset_allowed(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_password_reset when rate limit is not exceeded."""
        mock_redis_limiter.check_password_reset = AsyncMock(return_value=True)

        await auth_rate_limiter_service.check_password_reset("test@example.com")

        mock_redis_limiter.check_password_reset.assert_awaited_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_check_password_reset_exceeded(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test check_password_reset when rate limit is exceeded."""
        mock_redis_limiter.check_password_reset = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await auth_rate_limiter_service.check_password_reset("test@example.com")

        assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "3600 seconds" in exc_info.value.detail
        assert exc_info.value.headers == {"Retry-After": "3600"}

    @pytest.mark.asyncio
    async def test_record_failed_login(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test recording a failed login attempt."""
        mock_redis_limiter.record_failed_login = AsyncMock(return_value=3)

        failures = await auth_rate_limiter_service.record_failed_login("test@example.com")

        assert failures == 3
        mock_redis_limiter.record_failed_login.assert_awaited_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_clear_failed_logins(
        self,
        auth_rate_limiter_service: AuthRateLimiterService,
        mock_redis_limiter: MagicMock,
    ) -> None:
        """Test clearing failed login counter."""
        mock_redis_limiter.clear_failed_logins = AsyncMock()

        await auth_rate_limiter_service.clear_failed_logins("test@example.com")

        mock_redis_limiter.clear_failed_logins.assert_awaited_once_with("test@example.com")


class TestGetAuthRateLimiter:
    """Tests for get_auth_rate_limiter singleton factory."""

    def test_get_auth_rate_limiter_creates_instance(self) -> None:
        """Test that get_auth_rate_limiter creates a new instance."""
        reset_auth_rate_limiter()

        mock_settings = MagicMock()
        mock_settings.service_name = "test-service"
        mock_settings.redis.connection_string = "redis://localhost:6379/0"
        mock_settings.caching.rate_limit = AuthRateLimitConfig(
            login_per_minute=5,
            login_per_hour=20,
            register_per_hour=3,
            register_per_day=10,
            reset_per_hour=2,
        )

        with patch("user_auth_service.services.auth_rate_limiter.AuthRateLimiterService.create") as mock_create:
            mock_service = MagicMock(spec=AuthRateLimiterService)
            mock_create.return_value = mock_service

            limiter = get_auth_rate_limiter(mock_settings)

            assert limiter is mock_service
            mock_create.assert_called_once_with(
                cache_name="test-service",
                redis_url="redis://localhost:6379/0",
                config=mock_settings.caching.rate_limit,
            )

    def test_get_auth_rate_limiter_returns_singleton(self) -> None:
        """Test that get_auth_rate_limiter returns the same instance."""
        reset_auth_rate_limiter()

        mock_settings = MagicMock()
        mock_settings.service_name = "test-service"
        mock_settings.redis.connection_string = "redis://localhost:6379/0"
        mock_settings.caching.rate_limit = AuthRateLimitConfig(
            login_per_minute=5,
            login_per_hour=20,
            register_per_hour=3,
            register_per_day=10,
            reset_per_hour=2,
        )

        with patch("user_auth_service.services.auth_rate_limiter.AuthRateLimiterService.create") as mock_create:
            mock_service = MagicMock(spec=AuthRateLimiterService)
            mock_create.return_value = mock_service

            limiter1 = get_auth_rate_limiter(mock_settings)
            limiter2 = get_auth_rate_limiter(mock_settings)

            assert limiter1 is limiter2
            mock_create.assert_called_once()

    def test_reset_auth_rate_limiter(self) -> None:
        """Test that reset_auth_rate_limiter clears the global instance."""
        reset_auth_rate_limiter()

        mock_settings = MagicMock()
        mock_settings.service_name = "test-service"
        mock_settings.redis.connection_string = "redis://localhost:6379/0"
        mock_settings.caching.rate_limit = AuthRateLimitConfig(
            login_per_minute=5,
            login_per_hour=20,
            register_per_hour=3,
            register_per_day=10,
            reset_per_hour=2,
        )

        with patch("user_auth_service.services.auth_rate_limiter.AuthRateLimiterService.create") as mock_create:
            mock_service1 = MagicMock(spec=AuthRateLimiterService)
            mock_service2 = MagicMock(spec=AuthRateLimiterService)
            mock_create.side_effect = [mock_service1, mock_service2]

            limiter1 = get_auth_rate_limiter(mock_settings)
            reset_auth_rate_limiter()
            limiter2 = get_auth_rate_limiter(mock_settings)

            assert limiter1 is not limiter2
            assert mock_create.call_count == 2

"""Tests for token blacklist service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from user_auth_service.core.config import AuthCachingSettings, AuthTTLConfig
from user_auth_service.services.token_blacklist import (
    TokenBlacklist,
    get_token_blacklist,
    reset_token_blacklist,
)


@pytest.fixture
def mock_cache() -> AsyncMock:
    """Create a mock Redis cache."""
    cache = AsyncMock()
    cache.set = AsyncMock(return_value=None)
    cache.get = AsyncMock(return_value=None)
    cache.delete = AsyncMock(return_value=None)
    return cache


@pytest.fixture
def blacklist_ttl() -> int:
    """Return default blacklist TTL."""
    return 2592000  # 30 days


@pytest.fixture
def token_blacklist(mock_cache: AsyncMock, blacklist_ttl: int) -> TokenBlacklist:
    """Create TokenBlacklist instance with mock cache."""
    return TokenBlacklist(mock_cache, blacklist_ttl)


class TestTokenBlacklist:
    """Tests for TokenBlacklist class."""

    @pytest.mark.asyncio
    async def test_revoke_token(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
        blacklist_ttl: int,
    ) -> None:
        """Test revoking a token by JTI."""
        await token_blacklist.revoke("test-jti-123")

        mock_cache.set.assert_called_once_with(
            "token:blacklist:test-jti-123",
            "revoked",
            ttl=blacklist_ttl,
        )

    @pytest.mark.asyncio
    async def test_revoke_token_with_custom_ttl(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test revoking a token with custom TTL."""
        await token_blacklist.revoke("test-jti-123", expires_in=3600)

        mock_cache.set.assert_called_once_with(
            "token:blacklist:test-jti-123",
            "revoked",
            ttl=3600,
        )

    @pytest.mark.asyncio
    async def test_is_revoked_true(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test checking if a token is revoked (true case)."""
        mock_cache.get.return_value = "revoked"

        result = await token_blacklist.is_revoked("test-jti-123")

        assert result is True
        mock_cache.get.assert_called_once_with("token:blacklist:test-jti-123")

    @pytest.mark.asyncio
    async def test_is_revoked_false(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test checking if a token is revoked (false case)."""
        mock_cache.get.return_value = None

        result = await token_blacklist.is_revoked("test-jti-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_revoke_all_for_user(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
        blacklist_ttl: int,
    ) -> None:
        """Test revoking all tokens for a user."""
        await token_blacklist.revoke_all_for_user("user-123", 1704067200)

        mock_cache.set.assert_called_once_with(
            "user:revoke_all:user-123",
            "1704067200",
            ttl=blacklist_ttl,
        )

    @pytest.mark.asyncio
    async def test_is_user_token_revoked_no_revoke_event(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test checking user token when no revoke-all event exists."""
        mock_cache.get.return_value = None

        result = await token_blacklist.is_user_token_revoked("user-123", 1704067200)

        assert result is False

    @pytest.mark.asyncio
    async def test_is_user_token_revoked_before_event(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test checking user token issued before revoke-all event."""
        mock_cache.get.return_value = "1704100000"  # Revoke timestamp

        # Token issued at 1704067200 (before revoke at 1704100000)
        result = await token_blacklist.is_user_token_revoked("user-123", 1704067200)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_user_token_revoked_in_same_second(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Revoke-all invalidates tokens issued in the same timestamp second."""
        mock_cache.get.return_value = "1704067200"

        result = await token_blacklist.is_user_token_revoked("user-123", 1704067200)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_user_token_revoked_after_event(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test checking user token issued after revoke-all event."""
        mock_cache.get.return_value = "1704067200"  # Revoke timestamp

        # Token issued at 1704100000 (after revoke at 1704067200)
        result = await token_blacklist.is_user_token_revoked("user-123", 1704100000)

        assert result is False

    @pytest.mark.asyncio
    async def test_is_user_token_revoked_invalid_timestamp(
        self,
        token_blacklist: TokenBlacklist,
        mock_cache: AsyncMock,
    ) -> None:
        """Test checking user token with invalid stored timestamp."""
        mock_cache.get.return_value = "invalid"

        result = await token_blacklist.is_user_token_revoked("user-123", 1704067200)

        assert result is False


class TestGetTokenBlacklist:
    """Tests for get_token_blacklist factory function."""

    def test_get_token_blacklist_creates_instance(self) -> None:
        """Test that get_token_blacklist creates an instance."""
        reset_token_blacklist()

        mock_settings = MagicMock()
        mock_settings.service_name = "user-auth-service"
        mock_settings.redis.connection_string = "redis://localhost:6379"
        mock_settings.caching = AuthCachingSettings(ttls=AuthTTLConfig(token_blacklist=86400))

        # Factory creates instance with lazy Redis connection (no exception at creation)
        blacklist = get_token_blacklist(mock_settings)
        assert blacklist is not None
        assert isinstance(blacklist, TokenBlacklist)

        reset_token_blacklist()

    def test_get_token_blacklist_returns_singleton(self) -> None:
        """Test that get_token_blacklist returns the same instance."""
        reset_token_blacklist()

        mock_settings = MagicMock()
        mock_settings.service_name = "user-auth-service"
        mock_settings.redis.connection_string = "redis://localhost:6379"
        mock_settings.caching = AuthCachingSettings(ttls=AuthTTLConfig(token_blacklist=86400))

        blacklist1 = get_token_blacklist(mock_settings)
        blacklist2 = get_token_blacklist(mock_settings)
        assert blacklist1 is blacklist2

        reset_token_blacklist()

    def test_reset_token_blacklist(self) -> None:
        """Test that reset_token_blacklist resets the singleton."""
        reset_token_blacklist()

        from user_auth_service.services import token_blacklist

        assert token_blacklist._BlacklistHolder.instance is None


class TestAuthTTLConfig:
    """Tests for AuthTTLConfig class."""

    def test_default_token_blacklist_ttl(self) -> None:
        """Test default token blacklist TTL."""
        config = AuthTTLConfig()
        assert config.token_blacklist == 2592000  # 30 days

    def test_custom_token_blacklist_ttl(self) -> None:
        """Test custom token blacklist TTL."""
        config = AuthTTLConfig(token_blacklist=86400)
        assert config.token_blacklist == 86400

    def test_inherits_base_ttl_config(self) -> None:
        """Test that AuthTTLConfig inherits from CacheTTLConfig."""
        config = AuthTTLConfig()
        # Should have base class attributes
        assert hasattr(config, "short")
        assert hasattr(config, "medium")
        assert hasattr(config, "long")

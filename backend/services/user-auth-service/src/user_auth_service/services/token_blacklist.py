"""Token blacklist for JWT revocation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, create_cache

if TYPE_CHECKING:
    from user_auth_service.core.config import Settings

logger = get_logger(__name__)


class TokenBlacklist:
    """Redis-backed token blacklist for logout functionality.

    Stores JTI (JWT ID) claims of revoked tokens until they expire naturally.
    Also supports "revoke all tokens for user" functionality for logout-all-devices.
    """

    def __init__(self, cache: RedisCache, blacklist_ttl: int) -> None:
        """Initialize token blacklist with cache and TTL configuration."""
        self._cache = cache
        self._default_ttl = blacklist_ttl
        self._key_prefix = "token:blacklist"
        self._user_revoke_prefix = "user:revoke_all"

    async def revoke(self, jti: str, expires_in: int | None = None) -> None:
        """Add token to blacklist.

        Args:
            jti: JWT ID claim from the token
            expires_in: Seconds until token natural expiry (uses default TTL if None)

        """
        key = self._make_key(jti)
        ttl = expires_in if expires_in is not None else self._default_ttl
        await self._cache.set(key, "revoked", ttl=ttl)
        logger.info("Token revoked", jti=jti, ttl=ttl)

    async def is_revoked(self, jti: str) -> bool:
        """Check if token is blacklisted."""
        key = self._make_key(jti)
        result = await self._cache.get(key)
        return result is not None

    async def revoke_all_for_user(self, user_id: str, current_timestamp: int) -> None:
        """Revoke all tokens for a user (logout from all devices).

        This stores a "revoke all before" timestamp. Tokens issued before
        this timestamp are considered revoked.

        Args:
            user_id: User ID to revoke tokens for
            current_timestamp: Current Unix timestamp

        """
        key = f"{self._user_revoke_prefix}:{user_id}"
        await self._cache.set(key, str(current_timestamp), ttl=self._default_ttl)
        logger.info("All tokens revoked for user", user_id=user_id)

    async def is_user_token_revoked(self, user_id: str, issued_at: int) -> bool:
        """Check if a token predates or shares the second of a revoke-all event."""
        key = f"{self._user_revoke_prefix}:{user_id}"
        result = await self._cache.get(key)
        if result is None:
            return False
        try:
            revoke_timestamp = int(str(result))
        except ValueError, TypeError:
            return False
        else:
            return issued_at <= revoke_timestamp

    def _make_key(self, jti: str) -> str:
        return f"{self._key_prefix}:{jti}"


class _BlacklistHolder:
    """Singleton holder for TokenBlacklist."""

    instance: TokenBlacklist | None = None


def get_token_blacklist(settings: Settings) -> TokenBlacklist:
    """Get or create token blacklist instance."""
    if _BlacklistHolder.instance is None:
        cache = create_cache(
            settings.service_name,
            redis_url=settings.redis.connection_string,
        )
        _BlacklistHolder.instance = TokenBlacklist(cache, settings.caching.ttls.token_blacklist)
    return _BlacklistHolder.instance


def reset_token_blacklist() -> None:
    """Reset the token blacklist instance (for testing)."""
    _BlacklistHolder.instance = None

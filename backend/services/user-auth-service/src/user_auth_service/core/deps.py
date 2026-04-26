"""Shared FastAPI dependencies for user-auth-service.

Dependencies in this module can be used across multiple routers
without creating cross-router import dependencies.
"""

from __future__ import annotations

from nohiki_redis_utils import RedisCache, create_cache

from user_auth_service.core.config import get_settings
from user_auth_service.core.oauth_state import get_oauth_state_storage
from user_auth_service.services.oauth_service import OAuthService, get_oauth_service


class _OAuthSingletons:
    """Singleton holder for OAuth dependencies."""

    cache: RedisCache | None = None
    service: OAuthService | None = None


def _get_oauth_cache() -> RedisCache:
    """Get or create RedisCache for OAuth state storage."""
    if _OAuthSingletons.cache is None:
        settings = get_settings()
        _OAuthSingletons.cache = create_cache(
            settings.service_name,
            redis_url=settings.redis.connection_string,
        )
    return _OAuthSingletons.cache


def get_oauth_service_dep() -> OAuthService:
    """FastAPI dependency for OAuthService (singleton)."""
    if _OAuthSingletons.service is None:
        settings = get_settings()
        cache = _get_oauth_cache()
        state_storage = get_oauth_state_storage(settings, cache)
        _OAuthSingletons.service = get_oauth_service(settings, state_storage)
    return _OAuthSingletons.service

"""OAuth state storage using RedisCache with TTL."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from nohiki_redis_utils import RedisCache

    from user_auth_service.core.config import Settings
MIN_RETURN_URL_LENGTH = 1
MAX_RETURN_URL_LENGTH = 2048
CONTROL_CHARACTER_MIN = 32
DELETE_CHARACTER_CODE = 127


@dataclass(frozen=True, slots=True)
class OAuthState:
    """Immutable OAuth state data stored in Redis."""

    state: str
    code_verifier: str
    provider: str
    redirect_uri: str
    created_at: datetime
    return_url: str


def generate_state() -> str:
    """Generate cryptographically secure state parameter."""
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    """Generate PKCE code verifier (43-128 chars, base64url)."""
    return secrets.token_urlsafe(64)


def normalize_return_url(return_url: str | None) -> str:
    """Return a safe same-origin path, falling back to the application root."""
    if return_url is None or not MIN_RETURN_URL_LENGTH <= len(return_url) <= MAX_RETURN_URL_LENGTH:
        return "/"
    if not return_url.startswith("/") or return_url.startswith("//"):
        return "/"
    if "\\" in return_url or any(
        ord(char) < CONTROL_CHARACTER_MIN or ord(char) == DELETE_CHARACTER_CODE for char in return_url
    ):
        return "/"
    parsed = urlsplit(return_url)
    if parsed.scheme or parsed.netloc:
        return "/"
    return return_url


class OAuthStateStorage:
    """RedisCache-backed OAuth state storage with TTL."""

    KEY_PREFIX = "oauth_state:"
    _instance: OAuthStateStorage | None = None

    def __init__(self, cache: RedisCache, ttl_seconds: int = 600) -> None:
        """Initialize OAuth state storage.

        Args:
            cache: RedisCache instance for state persistence.
            ttl_seconds: Time-to-live for state entries in seconds.

        """
        self._cache = cache
        self._ttl = ttl_seconds

    @classmethod
    def get_instance(cls, cache: RedisCache, ttl_seconds: int) -> OAuthStateStorage:
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls(cache=cache, ttl_seconds=ttl_seconds)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        cls._instance = None

    def _key(self, state: str) -> str:
        """Generate Redis key for state."""
        return f"{self.KEY_PREFIX}{state}"

    async def store(
        self,
        provider: str,
        redirect_uri: str,
        return_url: str,
    ) -> OAuthState:
        """Generate and store OAuth state. Returns the state object."""
        state = generate_state()
        code_verifier = generate_code_verifier()
        now = datetime.now(tz=UTC)

        oauth_state = OAuthState(
            state=state,
            code_verifier=code_verifier,
            provider=provider,
            redirect_uri=redirect_uri,
            created_at=now,
            return_url=normalize_return_url(return_url),
        )

        data = json.dumps(
            {
                "code_verifier": code_verifier,
                "provider": provider,
                "redirect_uri": redirect_uri,
                "created_at": now.isoformat(),
                "return_url": oauth_state.return_url,
            }
        )

        await self._cache.set(self._key(state), data, ttl=self._ttl)

        return oauth_state

    async def retrieve_and_delete(self, state: str) -> OAuthState | None:
        """Atomically consume one-time state data, returning None if absent."""
        key = self._key(state)
        lock_name = f"oauth-state:{state}"
        lock_value = secrets.token_urlsafe(16)
        acquired = await self._cache.acquire_lock(
            lock_name,
            lock_value,
            ttl_seconds=5,
            timeout_seconds=2,
        )
        if not acquired:
            return None
        try:
            raw = await self._cache.get(key)
            if raw is None:
                return None
            await self._cache.delete(key)
        finally:
            await self._cache.release_lock(lock_name, lock_value)

        # RedisCache.get() returns deserialized dict or raw string
        raw_str = raw if isinstance(raw, str) else json.dumps(raw)
        data: dict[str, str] = json.loads(raw_str)

        return OAuthState(
            state=state,
            code_verifier=data["code_verifier"],
            provider=data["provider"],
            redirect_uri=data["redirect_uri"],
            created_at=datetime.fromisoformat(str(data["created_at"])),
            return_url=normalize_return_url(data["return_url"]),
        )


def get_oauth_state_storage(settings: Settings, cache: RedisCache) -> OAuthStateStorage:
    """Get or create OAuth state storage singleton."""
    return OAuthStateStorage.get_instance(
        cache=cache,
        ttl_seconds=settings.oauth.state_ttl,
    )


def reset_oauth_state_storage() -> None:
    """Reset OAuth state storage singleton (for testing)."""
    OAuthStateStorage.reset_instance()

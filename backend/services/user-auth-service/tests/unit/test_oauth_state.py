"""Unit tests for user_auth_service.core.oauth_state module."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Generator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from user_auth_service.core.oauth_state import (
    OAuthState,
    OAuthStateStorage,
    generate_code_verifier,
    generate_state,
    get_oauth_state_storage,
    normalize_return_url,
    reset_oauth_state_storage,
)

if TYPE_CHECKING:
    from nohiki_redis_utils import RedisCache


class TestGenerateState:
    """Tests for generate_state function."""

    def test_generates_unique_values(self) -> None:
        """Verify generate_state produces unique values on each call."""
        states = {generate_state() for _ in range(100)}
        assert len(states) == 100

    def test_returns_string(self) -> None:
        """Verify generate_state returns a string."""
        state = generate_state()
        assert isinstance(state, str)

    def test_state_length(self) -> None:
        """Verify generated state has reasonable length for URL safety."""
        state = generate_state()
        assert len(state) >= 32


class TestGenerateCodeVerifier:
    """Tests for generate_code_verifier function."""

    def test_generates_unique_values(self) -> None:
        """Verify generate_code_verifier produces unique values on each call."""
        verifiers = {generate_code_verifier() for _ in range(100)}
        assert len(verifiers) == 100

    def test_returns_string(self) -> None:
        """Verify generate_code_verifier returns a string."""
        verifier = generate_code_verifier()
        assert isinstance(verifier, str)

    def test_verifier_length_in_pkce_range(self) -> None:
        """Verify verifier length is within PKCE spec range (43-128 chars)."""
        verifier = generate_code_verifier()
        assert 43 <= len(verifier) <= 128


class TestOAuthState:
    """Tests for OAuthState dataclass."""

    def test_create_oauth_state(self) -> None:
        """Verify OAuthState can be created with all fields."""
        now = datetime.now(tz=UTC)
        state = OAuthState(
            state="test-state",
            code_verifier="test-verifier",
            provider="github",
            redirect_uri="http://localhost/callback",
            created_at=now,
            return_url="/dashboard",
        )

        assert state.state == "test-state"
        assert state.code_verifier == "test-verifier"
        assert state.provider == "github"
        assert state.redirect_uri == "http://localhost/callback"
        assert state.created_at == now

    def test_oauth_state_is_frozen_dataclass(self) -> None:
        """Verify OAuthState is a frozen dataclass."""
        assert dataclasses.is_dataclass(OAuthState)
        params = getattr(OAuthState, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class _AtomicStateCache:
    """Deterministic cache fake that exposes an unlocked get/delete race."""

    def __init__(self, raw: str) -> None:
        self.raw: str | None = raw
        self.locking_used = False
        self.lock_active = False
        self.get_arrivals = 0
        self.unlocked_gets_ready = asyncio.Event()

    async def acquire_lock(
        self,
        _name: str,
        _value: str,
        *,
        ttl_seconds: int,
        timeout_seconds: int,
    ) -> bool:
        self.locking_used = True
        if self.lock_active:
            return False
        self.lock_active = True
        return True

    async def release_lock(self, _name: str, _value: str) -> None:
        self.lock_active = False

    async def get(self, _key: str) -> str | None:
        if not self.locking_used:
            self.get_arrivals += 1
            if self.get_arrivals == 2:
                self.unlocked_gets_ready.set()
            await self.unlocked_gets_ready.wait()
        return self.raw

    async def delete(self, _key: str) -> None:
        self.raw = None


class TestOAuthStateStorage:
    """Tests for OAuthStateStorage class."""

    @pytest.fixture
    def mock_cache(self) -> AsyncMock:
        """Create a mock RedisCache client."""
        cache = AsyncMock()
        cache.set = AsyncMock()
        cache.get = AsyncMock(return_value=None)
        cache.delete = AsyncMock()
        cache.acquire_lock = AsyncMock(return_value=True)
        cache.release_lock = AsyncMock(return_value=None)
        return cache

    @pytest.fixture
    def storage(self, mock_cache: AsyncMock) -> OAuthStateStorage:
        """Create an OAuthStateStorage instance with mock RedisCache."""
        return OAuthStateStorage(cache=mock_cache, ttl_seconds=600)

    def test_key_prefix(self, storage: OAuthStateStorage) -> None:
        """Verify key prefix is used correctly."""
        key = storage._key("test-state")
        assert key == "oauth_state:test-state"

    @pytest.mark.asyncio
    async def test_store_creates_state(self, storage: OAuthStateStorage, mock_cache: AsyncMock) -> None:
        """Verify store creates and saves OAuth state to RedisCache."""
        result = await storage.store(
            provider="github", redirect_uri="http://localhost/callback", return_url="/dashboard?tab=jobs"
        )

        assert isinstance(result, OAuthState)
        assert result.provider == "github"
        assert result.redirect_uri == "http://localhost/callback"
        assert len(result.state) >= 32
        assert 43 <= len(result.code_verifier) <= 128

        mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_sets_ttl(self, storage: OAuthStateStorage, mock_cache: AsyncMock) -> None:
        """Verify store sets correct TTL on RedisCache key."""
        await storage.store(
            provider="github", redirect_uri="http://localhost/callback", return_url="/dashboard?tab=jobs"
        )

        set_call = mock_cache.set.call_args
        assert set_call.kwargs["ttl"] == 600

    @pytest.mark.asyncio
    async def test_retrieve_and_delete_returns_state(self, storage: OAuthStateStorage, mock_cache: AsyncMock) -> None:
        """Verify retrieve_and_delete returns stored state."""
        now = datetime.now(tz=UTC)
        stored_data = json.dumps(
            {
                "code_verifier": "test-verifier",
                "provider": "github",
                "redirect_uri": "http://localhost/callback",
                "created_at": now.isoformat(),
                "return_url": "/dashboard",
            }
        )
        mock_cache.get.return_value = stored_data

        result = await storage.retrieve_and_delete("test-state")

        assert result is not None
        assert result.state == "test-state"
        assert result.code_verifier == "test-verifier"
        assert result.provider == "github"
        assert result.redirect_uri == "http://localhost/callback"

    @pytest.mark.asyncio
    async def test_retrieve_and_delete_deletes_key(self, storage: OAuthStateStorage, mock_cache: AsyncMock) -> None:
        """Verify retrieve_and_delete removes the key from RedisCache."""
        now = datetime.now(tz=UTC)
        stored_data = json.dumps(
            {
                "code_verifier": "test-verifier",
                "provider": "github",
                "redirect_uri": "http://localhost/callback",
                "created_at": now.isoformat(),
                "return_url": "/dashboard",
            }
        )
        mock_cache.get.return_value = stored_data

        await storage.retrieve_and_delete("test-state")

        mock_cache.delete.assert_called_once_with("oauth_state:test-state")

    @pytest.mark.asyncio
    async def test_retrieve_and_delete_returns_none_when_not_found(
        self, storage: OAuthStateStorage, mock_cache: AsyncMock
    ) -> None:
        """Verify retrieve_and_delete returns None for missing state."""
        mock_cache.get.return_value = None

        result = await storage.retrieve_and_delete("nonexistent-state")

        assert result is None
        mock_cache.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_consume_returns_state_once(self) -> None:
        """Concurrent callbacks cannot both consume one OAuth state value."""
        raw = json.dumps(
            {
                "code_verifier": "test-verifier",
                "provider": "github",
                "redirect_uri": "http://localhost/callback",
                "created_at": datetime.now(tz=UTC).isoformat(),
                "return_url": "/dashboard",
            }
        )
        cache = _AtomicStateCache(raw)
        storage = OAuthStateStorage(cache=cast("RedisCache", cache), ttl_seconds=600)

        results = await asyncio.gather(
            storage.retrieve_and_delete("one-time-state"),
            storage.retrieve_and_delete("one-time-state"),
        )

        consumed = [result for result in results if result is not None]
        assert len(consumed) == 1
        assert consumed[0].state == "one-time-state"


class TestOAuthStateStorageSingleton:
    """Tests for OAuth state storage singleton management."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self) -> Generator[None]:
        """Reset singleton before each test."""
        reset_oauth_state_storage()
        yield
        reset_oauth_state_storage()

    def test_get_instance_creates_singleton(self) -> None:
        """Verify get_instance creates singleton."""
        mock_cache: AsyncMock = AsyncMock()
        storage1 = OAuthStateStorage.get_instance(cache=mock_cache, ttl_seconds=600)
        storage2 = OAuthStateStorage.get_instance(cache=mock_cache, ttl_seconds=300)

        assert storage1 is storage2

    def test_reset_instance_clears_singleton(self) -> None:
        """Verify reset_instance clears singleton."""
        mock_cache: AsyncMock = AsyncMock()
        storage1 = OAuthStateStorage.get_instance(cache=mock_cache, ttl_seconds=600)
        OAuthStateStorage.reset_instance()
        storage2 = OAuthStateStorage.get_instance(cache=mock_cache, ttl_seconds=600)

        assert storage1 is not storage2

    def test_get_oauth_state_storage_uses_settings(self) -> None:
        """Verify get_oauth_state_storage creates storage with settings."""
        mock_cache: AsyncMock = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.oauth.state_ttl = 900

        storage = get_oauth_state_storage(settings=mock_settings, cache=mock_cache)

        assert isinstance(storage, OAuthStateStorage)
        assert storage._ttl == 900

    def test_reset_oauth_state_storage_clears_singleton(self) -> None:
        """Verify reset_oauth_state_storage clears singleton via function."""
        mock_cache: AsyncMock = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.oauth.state_ttl = 600

        storage1 = get_oauth_state_storage(settings=mock_settings, cache=mock_cache)
        reset_oauth_state_storage()
        storage2 = get_oauth_state_storage(settings=mock_settings, cache=mock_cache)

        assert storage1 is not storage2


class TestNormalizeReturnUrl:
    @pytest.mark.parametrize("value", ["/", "/dashboard", "/jobs?tab=saved#top", "/a//b"])
    def test_accepts_local_paths(self, value: str) -> None:
        assert normalize_return_url(value) == value

    @pytest.mark.parametrize(
        "value",
        [None, "", "dashboard", "//evil.example/x", "/\\evil", "/x\nheader", "/x\x7f", "https://evil.example"],
    )
    def test_rejects_non_local_or_control_character_paths(self, value: str | None) -> None:
        assert normalize_return_url(value) == "/"

    def test_enforces_maximum_length(self) -> None:
        assert normalize_return_url("/" + "a" * 2047) != "/"
        assert normalize_return_url("/" + "a" * 2048) == "/"


@pytest.mark.asyncio
async def test_store_persists_only_normalized_return_url() -> None:
    cache = AsyncMock()
    storage = OAuthStateStorage(cache=cache, ttl_seconds=600)

    state = await storage.store("github", "https://api.example/callback", "//evil.example")

    payload = json.loads(cache.set.call_args.args[1])
    assert state.return_url == "/"
    assert payload["return_url"] == "/"
    assert "//evil.example" not in cache.set.call_args.args[1]

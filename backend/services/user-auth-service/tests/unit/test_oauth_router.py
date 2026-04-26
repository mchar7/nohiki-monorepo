"""Unit tests for user_auth_service.api.routers.oauth module."""

from __future__ import annotations

import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse
from nohiki_db_utils.testing import create_mock_session
from user_auth_service.api.routers.oauth import (
    PROVIDER_DISPLAY_NAMES,
    OAuthCallbackDeps,
    OAuthCallbackQuery,
    OAuthSessionParams,
    _build_error_redirect,
    _build_success_redirect,
    _create_session_and_response,
    _map_error_code,
    authorize,
    callback,
    get_providers,
)
from user_auth_service.api.schemas.oauth import (
    OAuthErrorCode,
    OAuthProvider,
    OAuthProviderInfo,
    OAuthProvidersResponse,
)
from user_auth_service.core.config import get_settings
from user_auth_service.core.cookies import get_oauth_state_cookie_name
from user_auth_service.core.jwt_rs256 import RS256JWTHandler
from user_auth_service.db.models import Account
from user_auth_service.services.oauth_service import OAuthError, OAuthResult


class TestProviderDisplayNames:
    """Tests for PROVIDER_DISPLAY_NAMES constant."""

    def test_has_all_providers(self) -> None:
        """All OAuth providers have display names."""
        for provider in OAuthProvider:
            assert provider in PROVIDER_DISPLAY_NAMES

    def test_display_names_are_capitalized(self) -> None:
        """Display names should be properly capitalized."""
        assert PROVIDER_DISPLAY_NAMES[OAuthProvider.GITHUB] == "GitHub"
        assert PROVIDER_DISPLAY_NAMES[OAuthProvider.GOOGLE] == "Google"


class TestBuildErrorRedirect:
    """Tests for _build_error_redirect helper."""

    def test_builds_correct_url(self) -> None:
        """Builds error redirect URL with query params."""
        url = _build_error_redirect(OAuthErrorCode.ACCESS_DENIED, "github")
        assert "error=access_denied" in url
        assert "provider=github" in url

    def test_uses_settings_error_redirect_url(self) -> None:
        """Uses error redirect URL from settings."""
        settings = get_settings()
        url = _build_error_redirect(OAuthErrorCode.SERVER_ERROR, "google")
        assert url.startswith(settings.oauth.error_redirect_url)

    def test_urlencodes_all_error_query_values(self) -> None:
        url = _build_error_redirect(OAuthErrorCode.SERVER_ERROR, "git hub&other")
        assert url.endswith("?error=server_error&provider=git+hub%26other")


class TestBuildSuccessRedirect:
    """Tests for _build_success_redirect helper."""

    def test_builds_url_with_encoded_backend_return_path(self) -> None:
        url = _build_success_redirect("/jobs?tab=saved&sort=new")
        assert (
            url
            == f"{get_settings().oauth.success_redirect_url}?success=true&returnUrl=%2Fjobs%3Ftab%3Dsaved%26sort%3Dnew"
        )


class TestMapErrorCode:
    """Tests for _map_error_code helper."""

    def test_maps_known_error_codes(self) -> None:
        """Maps known internal error codes to API error codes."""
        assert _map_error_code("state_mismatch") == OAuthErrorCode.STATE_MISMATCH
        assert _map_error_code("token_exchange_failed") == OAuthErrorCode.CODE_EXCHANGE_FAILED
        assert _map_error_code("profile_fetch_failed") == OAuthErrorCode.PROFILE_FETCH_FAILED
        assert _map_error_code("account_disabled") == OAuthErrorCode.ACCOUNT_DISABLED
        assert _map_error_code("access_denied") == OAuthErrorCode.ACCESS_DENIED

    def test_returns_server_error_for_unknown_codes(self) -> None:
        """Returns SERVER_ERROR for unknown error codes."""
        assert _map_error_code("unknown_error") == OAuthErrorCode.SERVER_ERROR
        assert _map_error_code("") == OAuthErrorCode.SERVER_ERROR


class TestGetProviders:
    """Tests for get_providers endpoint."""

    @pytest.mark.asyncio
    async def test_returns_all_providers(self) -> None:
        """Returns all OAuth providers with their status."""
        result = await get_providers()

        assert isinstance(result, OAuthProvidersResponse)
        assert len(result.providers) == len(OAuthProvider)

    @pytest.mark.asyncio
    async def test_providers_have_correct_structure(self) -> None:
        """Each provider has id, name, and enabled fields."""
        result = await get_providers()

        for provider_info in result.providers:
            assert isinstance(provider_info, OAuthProviderInfo)
            assert provider_info.id in OAuthProvider
            assert isinstance(provider_info.name, str)
            assert isinstance(provider_info.enabled, bool)

    @pytest.mark.asyncio
    async def test_disabled_providers_when_not_configured(self) -> None:
        """Providers are disabled when not configured."""
        settings = get_settings()
        result = await get_providers()

        for provider_info in result.providers:
            provider_settings = settings.oauth.get_provider(provider_info.id.value)
            if provider_settings is None or not provider_settings.is_configured():
                assert provider_info.enabled is False


class TestAuthorize:
    """Tests for authorize endpoint."""

    @staticmethod
    def _request(cookies: dict[str, str] | None = None) -> MagicMock:
        request = MagicMock(spec=Request)
        request.cookies = cookies or {}
        return request

    @pytest.mark.asyncio
    async def test_redirects_to_authorization_url(self) -> None:
        service = MagicMock()
        service.start_authorization = AsyncMock(return_value=("https://github.com/authorize?...", "browser-state"))

        result = await authorize(OAuthProvider.GITHUB, self._request(), service, "/jobs")

        assert isinstance(result, RedirectResponse)
        assert result.status_code == 302
        service.start_authorization.assert_awaited_once_with("github", "/jobs")
        name = get_oauth_state_cookie_name("browser-state", get_settings())
        assert result.headers["set-cookie"].startswith(f"{name}=browser-state;")

    @pytest.mark.asyncio
    async def test_two_authorizations_create_independent_binding_names(self) -> None:
        service = MagicMock()
        service.start_authorization = AsyncMock(
            side_effect=[("https://provider/one", "state-one"), ("https://provider/two", "state-two")]
        )

        first = await authorize(OAuthProvider.GITHUB, self._request(), service, "/one")
        second = await authorize(OAuthProvider.GITHUB, self._request(), service, "/two")

        settings = get_settings()
        first_name = get_oauth_state_cookie_name("state-one", settings)
        second_name = get_oauth_state_cookie_name("state-two", settings)
        assert first.headers["set-cookie"].startswith(f"{first_name}=state-one;")
        assert second.headers["set-cookie"].startswith(f"{second_name}=state-two;")
        assert first_name != second_name

    @pytest.mark.asyncio
    async def test_redirects_to_error_on_oauth_error(self) -> None:
        service = MagicMock()
        service.start_authorization = AsyncMock(side_effect=OAuthError("provider_disabled", "Provider not configured"))

        result = await authorize(OAuthProvider.GITHUB, self._request(), service, "/")

        assert isinstance(result, RedirectResponse)
        assert result.status_code == 302
        assert "error=" in str(result.headers.get("location", ""))


class TestCallback:
    def _deps(self, *, active: bool = True) -> OAuthCallbackDeps:
        account = MagicMock(spec=Account)
        account.id = uuid.uuid4()
        account.is_active = active
        oauth_result = OAuthResult(account=account, is_new_account=False, is_new_link=False)
        oauth_service = MagicMock()
        oauth_service.consume_callback_state = AsyncMock(
            return_value=MagicMock(return_url="/jobs?tab=saved", provider="github")
        )
        oauth_service.handle_callback = AsyncMock(return_value=oauth_result)
        db = create_mock_session()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        jwt = MagicMock(spec=RS256JWTHandler)
        jwt.create_access_token.return_value = "access.token"
        refresh = MagicMock()
        refresh.create_session = AsyncMock(return_value=("refresh.token", uuid.uuid4()))
        return OAuthCallbackDeps(oauth_service, db, jwt, refresh)

    def _request(self, *states: str) -> MagicMock:
        request = MagicMock(spec=Request)
        settings = get_settings()
        if not states:
            states = ("valid_state",)
        request.cookies = {get_oauth_state_cookie_name(state, settings): state for state in states}
        return request

    @staticmethod
    def _assert_binding_cleared(response: RedirectResponse, state: str = "valid_state") -> None:
        headers = response.headers.getlist("set-cookie")
        name = get_oauth_state_cookie_name(state, get_settings())
        assert any(header.startswith(f'{name}="";') and "Max-Age=0" in header for header in headers)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("error", "code", "expected"),
        [("access_denied", None, "access_denied"), (None, None, "state_mismatch")],
    )
    async def test_matching_state_is_consumed_before_provider_or_code_errors(
        self, error: str | None, code: str | None, expected: str
    ) -> None:
        deps = self._deps()
        result = await callback(
            self._request(),
            OAuthProvider.GITHUB,
            deps,
            OAuthCallbackQuery(code=code, state="valid_state", error=error),
        )

        cast(AsyncMock, deps.oauth_service.consume_callback_state).assert_awaited_once_with(
            "github", "valid_state", "valid_state"
        )
        cast(AsyncMock, deps.oauth_service.handle_callback).assert_not_awaited()
        assert f"error={expected}" in result.headers["location"]
        assert "returnUrl=" not in result.headers["location"]
        self._assert_binding_cleared(result)
        assert not any("nohiki_at=" in h or "nohiki_rt=" in h for h in result.headers.getlist("set-cookie"))

    @pytest.mark.asyncio
    async def test_mismatch_does_not_continue_and_clears_binding(self) -> None:
        deps = self._deps()
        cast(MagicMock, deps.oauth_service).consume_callback_state = AsyncMock(
            side_effect=OAuthError("state_mismatch", "wrong browser")
        )
        result = await callback(
            self._request("attacker"),
            OAuthProvider.GITHUB,
            deps,
            OAuthCallbackQuery(code="code", state="query"),
        )

        cast(AsyncMock, deps.oauth_service.handle_callback).assert_not_awaited()
        assert "error=state_mismatch&provider=github" in result.headers["location"]
        self._assert_binding_cleared(result, "query")

    @pytest.mark.asyncio
    async def test_success_uses_stored_encoded_return_path_and_clears_binding(self) -> None:
        deps = self._deps()
        result = await callback(
            self._request(),
            OAuthProvider.GITHUB,
            deps,
            OAuthCallbackQuery(code="code", state="valid_state"),
        )

        assert result.headers["location"].endswith("?success=true&returnUrl=%2Fjobs%3Ftab%3Dsaved")
        cast(AsyncMock, deps.oauth_service.handle_callback).assert_awaited_once()
        self._assert_binding_cleared(result)
        headers = result.headers.getlist("set-cookie")
        assert any("nohiki_at=" in header for header in headers)
        assert any("nohiki_rt=" in header for header in headers)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("order", [("state-one", "state-two"), ("state-two", "state-one")])
    async def test_two_bound_flows_complete_in_either_order(self, order: tuple[str, str]) -> None:
        settings = get_settings()
        all_states = ("state-one", "state-two")

        for state in order:
            deps = self._deps()
            cast(AsyncMock, deps.oauth_service.consume_callback_state).return_value = MagicMock(
                return_url=f"/{state}", provider="github"
            )
            result = await callback(
                self._request(*all_states),
                OAuthProvider.GITHUB,
                deps,
                OAuthCallbackQuery(code="code", state=state),
            )

            cast(AsyncMock, deps.oauth_service.consume_callback_state).assert_awaited_once_with("github", state, state)
            cleared = get_oauth_state_cookie_name(state, settings)
            other = get_oauth_state_cookie_name(next(value for value in all_states if value != state), settings)
            headers = result.headers.getlist("set-cookie")
            assert any(header.startswith(f'{cleared}="";') for header in headers)
            assert not any(header.startswith(f'{other}="";') for header in headers)

    @pytest.mark.asyncio
    async def test_all_handler_failures_clear_binding_without_auth_cookies(self) -> None:
        deps = self._deps(active=False)
        result = await callback(
            self._request(),
            OAuthProvider.GITHUB,
            deps,
            OAuthCallbackQuery(code="code", state="valid_state"),
        )

        assert "error=account_disabled&provider=github" in result.headers["location"]
        self._assert_binding_cleared(result)
        assert not any("nohiki_at=" in h or "nohiki_rt=" in h for h in result.headers.getlist("set-cookie"))

    @pytest.mark.asyncio
    async def test_missing_query_state_cannot_clear_an_unidentified_binding(self) -> None:
        deps = self._deps()
        result = await callback(
            self._request(),
            OAuthProvider.GITHUB,
            deps,
            OAuthCallbackQuery(code="code", state=None),
        )

        cast(AsyncMock, deps.oauth_service.consume_callback_state).assert_not_awaited()
        assert "error=state_mismatch&provider=github" in result.headers["location"]
        assert not result.headers.getlist("set-cookie")
        assert not any("nohiki_at=" in h or "nohiki_rt=" in h for h in result.headers.getlist("set-cookie"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (OAuthError("token_exchange_failed", "provider rejected code"), "code_exchange_failed"),
            (RuntimeError("unexpected"), "server_error"),
        ],
    )
    async def test_callback_exceptions_rollback_clear_binding_and_set_no_auth_cookies(
        self, failure: Exception, expected: str
    ) -> None:
        deps = self._deps()
        cast(MagicMock, deps.oauth_service).handle_callback = AsyncMock(side_effect=failure)

        result = await callback(
            self._request(),
            OAuthProvider.GITHUB,
            deps,
            OAuthCallbackQuery(code="code", state="valid_state"),
        )

        cast(AsyncMock, deps.db.rollback).assert_awaited_once()
        assert f"error={expected}&provider=github" in result.headers["location"]
        self._assert_binding_cleared(result)
        assert not any("nohiki_at=" in h or "nohiki_rt=" in h for h in result.headers.getlist("set-cookie"))


class TestOAuthSingletons:
    """Tests for OAuth singleton initialization."""

    def teardown_method(self) -> None:
        from user_auth_service.core.deps import _OAuthSingletons

        _OAuthSingletons.cache = None
        _OAuthSingletons.service = None

    def test_get_oauth_cache_creates_singleton(self) -> None:
        """Creates RedisCache on first call, returns same on second."""
        from user_auth_service.core.deps import _get_oauth_cache, _OAuthSingletons

        mock_cache = MagicMock()
        with (
            patch("user_auth_service.core.deps.create_cache", return_value=mock_cache),
            patch("user_auth_service.core.deps.get_settings") as mock_settings,
        ):
            mock_settings.return_value.service_name = "user-auth-service"
            mock_settings.return_value.redis.connection_string = "redis://localhost:6379/0"

            result = _get_oauth_cache()

        assert result is mock_cache
        assert _OAuthSingletons.cache is mock_cache

    def test_get_oauth_service_dep_creates_singleton(self) -> None:
        """Creates OAuthService on first call."""
        from user_auth_service.core.deps import _OAuthSingletons, get_oauth_service_dep

        mock_service = MagicMock()
        with (
            patch("user_auth_service.core.deps._get_oauth_cache", return_value=MagicMock()),
            patch("user_auth_service.core.deps.get_oauth_state_storage", return_value=MagicMock()),
            patch("user_auth_service.core.deps.get_oauth_service", return_value=mock_service),
            patch("user_auth_service.core.deps.get_settings"),
        ):
            result = get_oauth_service_dep()

        assert result is mock_service
        assert _OAuthSingletons.service is mock_service


class TestGetOAuthCallbackDeps:
    """Tests for get_oauth_callback_deps dependency bundler."""

    def test_bundles_all_dependencies(self) -> None:
        """Returns OAuthCallbackDeps with all provided dependencies."""
        from user_auth_service.api.routers.oauth import get_oauth_callback_deps

        mock_oauth = MagicMock()
        mock_db = create_mock_session()
        mock_jwt = MagicMock()
        mock_refresh = MagicMock()

        result = get_oauth_callback_deps(mock_oauth, mock_db, mock_jwt, mock_refresh)

        assert isinstance(result, OAuthCallbackDeps)
        assert result.oauth_service is mock_oauth
        assert result.db is mock_db
        assert result.jwt_handler is mock_jwt
        assert result.refresh_service is mock_refresh


class TestCreateSessionAndResponse:
    """Tests for _create_session_and_response helper."""

    @pytest.mark.asyncio
    async def test_creates_tokens_and_sets_cookies(self) -> None:
        """Creates access and refresh tokens and sets cookies."""
        mock_account = MagicMock(spec=Account)
        mock_account.id = uuid.uuid4()
        mock_account.is_active = True

        mock_result = OAuthResult(
            account=mock_account,
            is_new_account=True,
            is_new_link=True,
        )

        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()

        order: list[str] = []
        session_family_id = uuid.uuid4()
        mock_jwt_handler = MagicMock()
        mock_jwt_handler.create_access_token.side_effect = lambda *_args, **_kwargs: (
            order.append("access") or "access.token"
        )

        mock_refresh_service = MagicMock()
        mock_refresh_service.create_session = AsyncMock(
            side_effect=lambda *_args, **_kwargs: order.append("refresh") or ("refresh.token", session_family_id)
        )

        with (
            patch("user_auth_service.api.routers.oauth.set_access_token_cookie") as mock_set_access,
            patch("user_auth_service.api.routers.oauth.set_refresh_token_cookie") as mock_set_refresh,
        ):
            result = await _create_session_and_response(
                OAuthSessionParams(
                    result=mock_result,
                    provider="github",
                    return_url="/dashboard",
                    db=mock_db,
                    jwt_handler=mock_jwt_handler,
                    refresh_service=mock_refresh_service,
                )
            )

            mock_set_access.assert_called_once()
            mock_set_refresh.assert_called_once()

        assert isinstance(result, RedirectResponse)
        mock_jwt_handler.create_access_token.assert_called_once()
        mock_refresh_service.create_session.assert_awaited_once()
        mock_jwt_handler.create_access_token.assert_called_once_with(
            user_id=str(mock_account.id), session_family_id=str(session_family_id)
        )
        assert order == ["refresh", "access"]
        mock_db.commit.assert_awaited_once()

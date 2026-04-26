"""Unit tests for user_auth_service.core.cookies module."""

from __future__ import annotations

from fastapi import Response
from user_auth_service.core.config import CookieSettings, JWTSettings, get_settings
from user_auth_service.core.cookies import (
    MAX_OAUTH_STATE_COOKIES,
    clear_auth_cookies,
    clear_excess_oauth_state_cookies,
    clear_oauth_state_cookie,
    get_access_token_from_cookie,
    get_oauth_state_cookie_name,
    get_oauth_state_from_cookie,
    get_refresh_token_from_cookie,
    set_access_token_cookie,
    set_oauth_state_cookie,
    set_refresh_token_cookie,
)


class TestSetAccessTokenCookie:
    """Tests for set_access_token_cookie function."""

    def test_sets_access_token_cookie_with_defaults(self) -> None:
        """Sets access token cookie with default settings."""
        response = Response()
        settings = get_settings()
        token = "test.access.token"

        set_access_token_cookie(response, token, settings)

        # The cookie should be HttpOnly and Secure (in default settings)
        cookie_header = next(
            (h for h in response.raw_headers if h[0] == b"set-cookie"),
            None,
        )
        assert cookie_header is not None
        cookie_value = cookie_header[1].decode()
        assert settings.cookie.access_token_name in cookie_value
        assert token in cookie_value
        assert "HttpOnly" in cookie_value
        assert "SameSite=lax" in cookie_value
        assert f"Max-Age={settings.jwt.access_token_expire_minutes * 60}" in cookie_value

    def test_sets_access_token_cookie_with_custom_settings(self) -> None:
        """Sets access token cookie with custom settings."""
        response = Response()
        # Create custom settings with custom JWT and Cookie configurations
        custom_jwt = JWTSettings(access_token_expire_minutes=15)
        custom_cookie = CookieSettings(
            access_token_name="custom_access",
            samesite="strict",
        )
        settings = get_settings()
        # Replace nested settings
        settings.jwt = custom_jwt
        settings.cookie = custom_cookie

        token = "custom.access.token"

        set_access_token_cookie(response, token, settings)

        cookie_header = next(
            (h for h in response.raw_headers if h[0] == b"set-cookie"),
            None,
        )
        assert cookie_header is not None
        cookie_value = cookie_header[1].decode()
        assert "custom_access" in cookie_value
        assert token in cookie_value
        assert "SameSite=strict" in cookie_value
        assert "Max-Age=900" in cookie_value  # 15 * 60


class TestSetRefreshTokenCookie:
    """Tests for set_refresh_token_cookie function."""

    def test_sets_refresh_token_cookie_with_defaults(self) -> None:
        """Sets refresh token cookie with default settings."""
        response = Response()
        settings = get_settings()
        token = "test.refresh.token"

        set_refresh_token_cookie(response, token, settings)

        cookie_header = next(
            (h for h in response.raw_headers if h[0] == b"set-cookie"),
            None,
        )
        assert cookie_header is not None
        cookie_value = cookie_header[1].decode()
        assert token in cookie_value
        assert "HttpOnly" in cookie_value
        # SameSite should be present (value depends on current settings state)
        assert "SameSite=" in cookie_value
        # 30 days * 24 hours * 60 minutes * 60 seconds
        expected_max_age = settings.jwt.refresh_token_expire_days * 24 * 60 * 60
        assert f"Max-Age={expected_max_age}" in cookie_value

    def test_sets_refresh_token_cookie_with_custom_settings(self) -> None:
        """Sets refresh token cookie with custom settings."""
        response = Response()
        # Create custom settings
        custom_jwt = JWTSettings(refresh_token_expire_days=7)
        custom_cookie = CookieSettings(
            refresh_token_name="custom_refresh",
            samesite="none",
        )
        settings = get_settings()
        settings.jwt = custom_jwt
        settings.cookie = custom_cookie

        token = "custom.refresh.token"

        set_refresh_token_cookie(response, token, settings)

        cookie_header = next(
            (h for h in response.raw_headers if h[0] == b"set-cookie"),
            None,
        )
        assert cookie_header is not None
        cookie_value = cookie_header[1].decode()
        assert "custom_refresh" in cookie_value
        assert token in cookie_value
        assert "SameSite=none" in cookie_value
        # 7 days * 24 * 60 * 60
        assert "Max-Age=604800" in cookie_value


class TestClearAuthCookies:
    """Tests for clear_auth_cookies function."""

    def test_clears_both_access_and_refresh_cookies(self) -> None:
        """Clears both access and refresh token cookies."""
        response = Response()
        settings = get_settings()

        clear_auth_cookies(response, settings)

        # Both cookies should be deleted (Max-Age=0)
        cookie_headers = [h[1].decode() for h in response.raw_headers if h[0] == b"set-cookie"]
        assert len(cookie_headers) == 2
        # Check that both cookies are being cleared
        access_cleared = any(settings.cookie.access_token_name in h and "Max-Age=0" in h for h in cookie_headers)
        refresh_cleared = any(settings.cookie.refresh_token_name in h and "Max-Age=0" in h for h in cookie_headers)
        assert access_cleared
        assert refresh_cleared

    def test_clears_cookies_with_correct_attributes(self) -> None:
        """Ensures cookies are cleared with matching security attributes."""
        response = Response()
        # Create custom cookie settings with domain
        custom_cookie = CookieSettings(
            domain="example.com",
            secure=True,
            samesite="strict",
        )
        settings = get_settings()
        settings.cookie = custom_cookie

        clear_auth_cookies(response, settings)

        cookie_headers = [h[1].decode() for h in response.raw_headers if h[0] == b"set-cookie"]
        for cookie in cookie_headers:
            assert "Max-Age=0" in cookie
            # Domain should be set when specified
            assert "Domain=example.com" in cookie
            assert "Secure" in cookie
            assert "HttpOnly" in cookie
            # SameSite should be strict as specified
            assert "SameSite=strict" in cookie


class TestGetAccessTokenFromCookie:
    """Tests for get_access_token_from_cookie function."""

    def test_returns_token_when_present(self) -> None:
        """Returns access token when present in cookies."""
        settings = get_settings()
        cookies = {settings.cookie.access_token_name: "test.access.token"}

        result = get_access_token_from_cookie(cookies, settings)

        assert result == "test.access.token"

    def test_returns_none_when_cookie_not_present(self) -> None:
        """Returns None when access token cookie is not present."""
        settings = get_settings()
        cookies: dict[str, str] = {}

        result = get_access_token_from_cookie(cookies, settings)

        assert result is None

    def test_returns_none_when_wrong_cookie_name(self) -> None:
        """Returns None when cookie has different name."""
        settings = get_settings()
        cookies = {"wrong_cookie_name": "test.access.token"}

        result = get_access_token_from_cookie(cookies, settings)

        assert result is None


class TestGetRefreshTokenFromCookie:
    """Tests for get_refresh_token_from_cookie function."""

    def test_returns_token_when_present(self) -> None:
        """Returns refresh token when present in cookies."""
        settings = get_settings()
        cookies = {settings.cookie.refresh_token_name: "test.refresh.token"}

        result = get_refresh_token_from_cookie(cookies, settings)

        assert result == "test.refresh.token"

    def test_returns_none_when_cookie_not_present(self) -> None:
        """Returns None when refresh token cookie is not present."""
        settings = get_settings()
        cookies: dict[str, str] = {}

        result = get_refresh_token_from_cookie(cookies, settings)

        assert result is None

    def test_returns_none_when_wrong_cookie_name(self) -> None:
        """Returns None when cookie has different name."""
        settings = get_settings()
        cookies = {"wrong_cookie_name": "test.refresh.token"}

        result = get_refresh_token_from_cookie(cookies, settings)

        assert result is None


class TestCookieIntegration:
    """Integration tests for cookie operations."""

    def test_set_and_get_access_token_roundtrip(self) -> None:
        """Tests setting and retrieving access token."""
        response = Response()
        settings = get_settings()
        token = "roundtrip.access.token"

        set_access_token_cookie(response, token, settings)

        # Simulate extracting cookies from response
        # In real scenario, this would be parsed from Set-Cookie headers
        cookies = {settings.cookie.access_token_name: token}
        retrieved = get_access_token_from_cookie(cookies, settings)

        assert retrieved == token

    def test_set_and_get_refresh_token_roundtrip(self) -> None:
        """Tests setting and retrieving refresh token."""
        response = Response()
        settings = get_settings()
        token = "roundtrip.refresh.token"

        set_refresh_token_cookie(response, token, settings)

        cookies = {settings.cookie.refresh_token_name: token}
        retrieved = get_refresh_token_from_cookie(cookies, settings)

        assert retrieved == token

    def test_clear_removes_both_tokens(self) -> None:
        """Tests that clearing cookies affects both tokens."""
        response = Response()
        settings = get_settings()

        # First set both cookies
        set_access_token_cookie(response, "access.token", settings)
        set_refresh_token_cookie(response, "refresh.token", settings)

        # Now clear them
        clear_response = Response()
        clear_auth_cookies(clear_response, settings)

        # Both should be cleared (have Max-Age=0)
        clear_headers = [h[1].decode() for h in clear_response.raw_headers if h[0] == b"set-cookie"]
        assert all("Max-Age=0" in h for h in clear_headers)


class TestOAuthStateCookie:
    def test_sets_exact_host_only_binding_attributes(self) -> None:
        response = Response()
        settings = get_settings()

        set_oauth_state_cookie(response, "browser-state", settings)

        name = get_oauth_state_cookie_name("browser-state", settings)
        header = response.headers["set-cookie"]
        assert header.startswith(f"{name}=browser-state;")
        assert "HttpOnly" in header
        assert "Path=/" in header
        assert "SameSite=lax" in header
        assert f"Max-Age={settings.oauth.state_ttl}" in header
        assert ("Secure" in header) is settings.cookie.secure
        assert "Domain=" not in header

    def test_clears_only_matching_binding(self) -> None:
        response = Response()
        settings = get_settings()
        first_name = get_oauth_state_cookie_name("first", settings)
        second_name = get_oauth_state_cookie_name("second", settings)

        clear_oauth_state_cookie(response, "first", settings)

        header = response.headers["set-cookie"]
        assert header.startswith(f'{first_name}="";')
        assert second_name not in header
        assert "Max-Age=0" in header
        assert "Domain=" not in header

    def test_reads_only_binding_derived_from_active_state(self) -> None:
        settings = get_settings()
        first_name = get_oauth_state_cookie_name("first", settings)
        second_name = get_oauth_state_cookie_name("second", settings)
        cookies = {first_name: "first", second_name: "second"}

        assert get_oauth_state_from_cookie(cookies, "first", settings) == "first"
        assert get_oauth_state_from_cookie(cookies, "unknown", settings) is None

    def test_active_cookie_bound_evicts_only_oldest_excess_bindings(self) -> None:
        response = Response()
        settings = get_settings()
        states = [f"state-{index}" for index in range(MAX_OAUTH_STATE_COOKIES + 2)]
        cookies = {get_oauth_state_cookie_name(state, settings): state for state in states}

        clear_excess_oauth_state_cookies(response, cookies, settings)

        headers = response.headers.getlist("set-cookie")
        evicted = [get_oauth_state_cookie_name(state, settings) for state in states[:3]]
        retained = [get_oauth_state_cookie_name(state, settings) for state in states[3:]]
        assert len(headers) == 3
        assert all(any(header.startswith(f'{name}="";') for header in headers) for name in evicted)
        assert all(not any(header.startswith(f'{name}="";') for header in headers) for name in retained)

    def test_host_prefixed_oauth_cookie_never_emits_domain(self) -> None:
        settings = get_settings().model_copy(deep=True)
        settings.cookie = CookieSettings(oauth_state_name="__Host-oauth-state", domain="example.com")
        response = Response()

        set_oauth_state_cookie(response, "state", settings)
        clear_oauth_state_cookie(response, "state", settings)
        clear_excess_oauth_state_cookies(
            response,
            {get_oauth_state_cookie_name("old", settings): "old"},
            settings,
        )

        assert all("Domain=" not in header for header in response.headers.getlist("set-cookie"))

"""Unit tests for user_auth_service.core.oauth_clients module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr
from user_auth_service.core.config import (
    GitHubOAuthSettings,
    GoogleOAuthSettings,
    OAuthSettings,
)
from user_auth_service.core.oauth_clients import (
    SUPPORTED_PROVIDERS,
    GitHubOAuthClient,
    GoogleOAuthClient,
    OAuthProvider,
    OAuthUserProfile,
    create_oauth_client,
    create_pkce_challenge,
    is_valid_provider,
)


class TestOAuthProvider:
    """Tests for OAuthProvider enum."""

    def test_github_provider_value(self) -> None:
        """Verify GitHub provider has correct value."""
        assert OAuthProvider.GITHUB.value == "github"

    def test_google_provider_value(self) -> None:
        """Verify Google provider has correct value."""
        assert OAuthProvider.GOOGLE.value == "google"


class TestSupportedProviders:
    """Tests for SUPPORTED_PROVIDERS constant."""

    def test_contains_github(self) -> None:
        """Verify SUPPORTED_PROVIDERS contains GitHub."""
        assert OAuthProvider.GITHUB in SUPPORTED_PROVIDERS

    def test_contains_google(self) -> None:
        """Verify SUPPORTED_PROVIDERS contains Google."""
        assert OAuthProvider.GOOGLE in SUPPORTED_PROVIDERS

    def test_is_frozenset(self) -> None:
        """Verify SUPPORTED_PROVIDERS is a frozenset."""
        assert isinstance(SUPPORTED_PROVIDERS, frozenset)


class TestIsValidProvider:
    """Tests for is_valid_provider function."""

    def test_valid_github_provider(self) -> None:
        """Verify is_valid_provider returns True for GitHub."""
        assert is_valid_provider("github") is True

    def test_valid_google_provider(self) -> None:
        """Verify is_valid_provider returns True for Google."""
        assert is_valid_provider("google") is True

    def test_invalid_provider(self) -> None:
        """Verify is_valid_provider returns False for unknown provider."""
        assert is_valid_provider("unknown") is False

    def test_case_sensitive(self) -> None:
        """Verify is_valid_provider is case-sensitive."""
        assert is_valid_provider("GitHub") is False
        assert is_valid_provider("GOOGLE") is False


class TestCreatePkceChallenge:
    """Tests for create_pkce_challenge function."""

    def test_creates_challenge_from_verifier(self) -> None:
        """Verify create_pkce_challenge produces valid S256 challenge."""
        verifier = "test-verifier-string-that-is-long-enough-for-pkce"
        challenge = create_pkce_challenge(verifier)

        assert isinstance(challenge, str)
        assert len(challenge) > 0

    def test_challenge_is_url_safe(self) -> None:
        """Verify challenge uses URL-safe base64 (no padding)."""
        verifier = "test-verifier-string-that-is-long-enough-for-pkce"
        challenge = create_pkce_challenge(verifier)

        assert "=" not in challenge
        assert "+" not in challenge
        assert "/" not in challenge

    def test_same_verifier_produces_same_challenge(self) -> None:
        """Verify same verifier always produces same challenge."""
        verifier = "test-verifier-string-that-is-long-enough-for-pkce"
        challenge1 = create_pkce_challenge(verifier)
        challenge2 = create_pkce_challenge(verifier)

        assert challenge1 == challenge2

    def test_different_verifiers_produce_different_challenges(self) -> None:
        """Verify different verifiers produce different challenges."""
        verifier1 = "test-verifier-one-that-is-long-enough-for-pkce"
        verifier2 = "test-verifier-two-that-is-long-enough-for-pkce"

        challenge1 = create_pkce_challenge(verifier1)
        challenge2 = create_pkce_challenge(verifier2)

        assert challenge1 != challenge2


class TestOAuthUserProfile:
    """Tests for OAuthUserProfile dataclass."""

    def test_create_profile(self) -> None:
        """Verify OAuthUserProfile can be created."""
        profile = OAuthUserProfile(
            provider=OAuthProvider.GITHUB,
            provider_user_id="12345",
            email="user@example.com",
            username="testuser",
            display_name="Test User",
            raw_profile={"id": 12345},
        )

        assert profile.provider == OAuthProvider.GITHUB
        assert profile.provider_user_id == "12345"
        assert profile.email == "user@example.com"
        assert profile.username == "testuser"
        assert profile.display_name == "Test User"

    def test_profile_with_none_email(self) -> None:
        """Verify OAuthUserProfile handles None email."""
        profile = OAuthUserProfile(
            provider=OAuthProvider.GOOGLE,
            provider_user_id="sub-123",
            email=None,
            username=None,
            display_name="Test User",
            raw_profile={},
        )

        assert profile.email is None
        assert profile.username is None


class TestGitHubOAuthClient:
    """Tests for GitHubOAuthClient."""

    @pytest.fixture
    def github_settings(self) -> GitHubOAuthSettings:
        """Create GitHub OAuth settings."""
        return GitHubOAuthSettings(
            client_id="test-client-id",
            client_secret=SecretStr("test-client-secret"),
        )

    def test_client_initialization(self, github_settings: GitHubOAuthSettings) -> None:
        """Verify GitHubOAuthClient initializes correctly."""
        client = GitHubOAuthClient(github_settings)

        assert client._client_id == "test-client-id"
        assert client._client_secret == "test-client-secret"
        assert client._userinfo_url == "https://api.github.com/user"
        assert client._emails_url == "https://api.github.com/user/emails"

    def test_get_authorization_url(self, github_settings: GitHubOAuthSettings) -> None:
        """Verify get_authorization_url returns valid URL."""
        client = GitHubOAuthClient(github_settings)

        url = client.get_authorization_url(
            redirect_uri="http://localhost/callback",
            state="test-state",
            code_verifier="test-verifier-that-is-long-enough-for-pkce",
        )

        assert isinstance(url, str)
        assert "https://github.com/login/oauth/authorize" in url
        assert "client_id=test-client-id" in url
        assert "state=test-state" in url
        assert "code_challenge=" in url

    @pytest.mark.asyncio
    async def test_fetch_user_profile(self, github_settings: GitHubOAuthSettings) -> None:
        """Verify fetch_user_profile returns OAuthUserProfile."""
        client = GitHubOAuthClient(github_settings)

        with patch("user_auth_service.core.oauth_clients.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_user_response = MagicMock()
            mock_user_response.json.return_value = {
                "id": 12345,
                "login": "testuser",
                "name": "Test User",
            }

            mock_emails_response = MagicMock()
            mock_emails_response.json.return_value = [
                {
                    "email": "user@example.com",
                    "primary": True,
                    "verified": True,
                }
            ]

            mock_client.get.side_effect = [mock_user_response, mock_emails_response]

            profile = await client.fetch_user_profile("test-access-token")

            assert profile.provider == OAuthProvider.GITHUB
            assert profile.provider_user_id == "12345"
            assert profile.username == "testuser"
            assert profile.display_name == "Test User"
            assert profile.email == "user@example.com"

    def test_extract_primary_email(self) -> None:
        """Verify _extract_primary_email returns primary verified email."""
        emails = [
            {"email": "secondary@example.com", "primary": False, "verified": True},
            {"email": "primary@example.com", "primary": True, "verified": True},
            {"email": "unverified@example.com", "primary": False, "verified": False},
        ]

        result = GitHubOAuthClient._extract_primary_email(emails)

        assert result == "primary@example.com"

    def test_extract_primary_email_no_verified(self) -> None:
        """Verify _extract_primary_email returns None if no verified email."""
        emails = [
            {"email": "unverified@example.com", "primary": True, "verified": False},
        ]

        result = GitHubOAuthClient._extract_primary_email(emails)

        assert result is None


class TestGoogleOAuthClient:
    """Tests for GoogleOAuthClient."""

    @pytest.fixture
    def google_settings(self) -> GoogleOAuthSettings:
        """Create Google OAuth settings."""
        return GoogleOAuthSettings(
            client_id="test-client-id",
            client_secret=SecretStr("test-client-secret"),
        )

    def test_client_initialization(self, google_settings: GoogleOAuthSettings) -> None:
        """Verify GoogleOAuthClient initializes correctly."""
        client = GoogleOAuthClient(google_settings)

        assert client._client_id == "test-client-id"
        assert client._client_secret == "test-client-secret"
        assert client._userinfo_url == "https://www.googleapis.com/oauth2/v3/userinfo"

    def test_get_authorization_url(self, google_settings: GoogleOAuthSettings) -> None:
        """Verify get_authorization_url returns valid URL."""
        client = GoogleOAuthClient(google_settings)

        url = client.get_authorization_url(
            redirect_uri="http://localhost/callback",
            state="test-state",
            code_verifier="test-verifier-that-is-long-enough-for-pkce",
        )

        assert isinstance(url, str)
        assert "https://accounts.google.com/o/oauth2/v2/auth" in url
        assert "client_id=test-client-id" in url
        assert "state=test-state" in url

    @pytest.mark.asyncio
    async def test_fetch_user_profile(self, google_settings: GoogleOAuthSettings) -> None:
        """Verify fetch_user_profile returns OAuthUserProfile."""
        client = GoogleOAuthClient(google_settings)

        with patch("user_auth_service.core.oauth_clients.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "sub": "google-user-id",
                "email": "user@example.com",
                "email_verified": True,
                "name": "Test User",
            }

            mock_client.get.return_value = mock_response

            profile = await client.fetch_user_profile("test-access-token")

            assert profile.provider == OAuthProvider.GOOGLE
            assert profile.provider_user_id == "google-user-id"
            assert profile.email == "user@example.com"
            assert profile.display_name == "Test User"

    @pytest.mark.asyncio
    async def test_fetch_user_profile_unverified_email(self, google_settings: GoogleOAuthSettings) -> None:
        """Verify fetch_user_profile returns None for unverified email."""
        client = GoogleOAuthClient(google_settings)

        with patch("user_auth_service.core.oauth_clients.httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__.return_value = mock_client

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "sub": "google-user-id",
                "email": "user@example.com",
                "email_verified": False,
                "name": "Test User",
            }

            mock_client.get.return_value = mock_response

            profile = await client.fetch_user_profile("test-access-token")

            assert profile.email is None


class TestCreateOAuthClient:
    """Tests for create_oauth_client factory function."""

    def test_create_github_client(self) -> None:
        """Verify create_oauth_client creates GitHubOAuthClient."""
        settings = OAuthSettings(
            github=GitHubOAuthSettings(
                client_id="test-id",
                client_secret=SecretStr("test-secret"),
            )
        )

        client = create_oauth_client(OAuthProvider.GITHUB, settings)

        assert isinstance(client, GitHubOAuthClient)

    def test_create_google_client(self) -> None:
        """Verify create_oauth_client creates GoogleOAuthClient."""
        settings = OAuthSettings(
            google=GoogleOAuthSettings(
                client_id="test-id",
                client_secret=SecretStr("test-secret"),
            )
        )

        client = create_oauth_client(OAuthProvider.GOOGLE, settings)

        assert isinstance(client, GoogleOAuthClient)

    def test_create_unknown_provider_raises(self) -> None:
        """Raises ValueError when provider settings not found."""
        mock_settings = MagicMock(spec=OAuthSettings)
        mock_settings.get_provider.return_value = None

        with pytest.raises(ValueError, match="Unknown OAuth provider"):
            create_oauth_client(OAuthProvider.GITHUB, mock_settings)


class TestBaseOAuthClientExchangeCode:
    """Tests for BaseOAuthClient.exchange_code method."""

    @pytest.mark.asyncio
    async def test_exchange_code_returns_token_dict(self) -> None:
        """exchange_code returns token data from provider."""
        settings = GitHubOAuthSettings(
            client_id="test-id",
            client_secret=SecretStr("test-secret"),
        )
        client = GitHubOAuthClient(settings)

        mock_async_client = MagicMock()
        mock_token = {"access_token": "tok", "token_type": "bearer"}
        mock_async_client.fetch_token = AsyncMock(return_value=mock_token)

        with patch.object(client, "_create_async_client", return_value=mock_async_client):
            result = await client.exchange_code(
                code="auth-code",
                redirect_uri="http://localhost/callback",
                code_verifier="verifier",
            )

        assert result == {"access_token": "tok", "token_type": "bearer"}
        mock_async_client.fetch_token.assert_awaited_once()

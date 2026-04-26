"""OAuth provider client factory using Authlib."""

from __future__ import annotations

import base64
import hashlib
import importlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, assert_never, cast

import httpx

from user_auth_service.api.schemas.oauth import OAuthProvider
from user_auth_service.core.config import GitHubOAuthSettings, GoogleOAuthSettings

if TYPE_CHECKING:
    from user_auth_service.core.config import OAuthSettings


SUPPORTED_PROVIDERS: frozenset[OAuthProvider] = frozenset(OAuthProvider)


def is_valid_provider(provider: str) -> bool:
    """Check if provider is supported. O(1) lookup."""
    return provider in SUPPORTED_PROVIDERS


@dataclass(frozen=True, slots=True)
class OAuthUserProfile:
    """Normalized user profile from OAuth provider."""

    provider: OAuthProvider
    provider_user_id: str
    email: str | None
    username: str | None
    display_name: str | None
    raw_profile: dict[str, Any]


def create_pkce_challenge(code_verifier: str) -> str:
    """Create PKCE code challenge from verifier (S256 method)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuth2ClientProtocol(Protocol):
    """Protocol for Authlib AsyncOAuth2Client interactions."""

    def create_authorization_url(
        self,
        authorize_url: str,
        *,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
        scope: str,
    ) -> tuple[str, str]:
        """Create authorization URL and state."""

    async def fetch_token(
        self,
        access_token_url: str,
        *,
        code: str,
        code_verifier: str,
    ) -> dict[str, object]:
        """Fetch OAuth token response."""


class BaseOAuthClient:
    """Base OAuth client with common functionality."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        authorize_url: str,
        access_token_url: str,
        scopes: tuple[str, ...],
    ) -> None:
        """Initialize OAuth client.

        Args:
            client_id: OAuth application client ID.
            client_secret: OAuth application client secret.
            authorize_url: Provider's authorization endpoint URL.
            access_token_url: Provider's token endpoint URL.
            scopes: OAuth scopes to request.

        """
        self._client_id = client_id
        self._client_secret = client_secret
        self._authorize_url = authorize_url
        self._access_token_url = access_token_url
        self._scopes = scopes

    def _create_async_client(self, redirect_uri: str) -> OAuth2ClientProtocol:
        module = importlib.import_module("authlib.integrations.httpx_client")
        client_class = module.AsyncOAuth2Client
        client = client_class(
            client_id=self._client_id,
            client_secret=self._client_secret,
            redirect_uri=redirect_uri,
        )
        return cast(OAuth2ClientProtocol, client)

    def get_authorization_url(
        self,
        redirect_uri: str,
        state: str,
        code_verifier: str,
    ) -> str:
        """Generate authorization URL with PKCE."""
        code_challenge = create_pkce_challenge(code_verifier)

        client = self._create_async_client(redirect_uri)

        url, _ = client.create_authorization_url(
            self._authorize_url,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            scope=" ".join(self._scopes),
        )
        return str(url)

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        client = self._create_async_client(redirect_uri)

        token = await client.fetch_token(
            self._access_token_url,
            code=code,
            code_verifier=code_verifier,
        )
        return dict(token)


class GitHubOAuthClient(BaseOAuthClient):
    """GitHub-specific OAuth client."""

    def __init__(self, settings: GitHubOAuthSettings) -> None:
        """Initialize GitHub OAuth client.

        Args:
            settings: GitHub OAuth provider settings.

        """
        super().__init__(
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            authorize_url=settings.authorize_url,
            access_token_url=settings.access_token_url,
            scopes=settings.scopes,
        )
        self._userinfo_url = settings.userinfo_url
        self._emails_url = settings.emails_url

    async def fetch_user_profile(self, access_token: str) -> OAuthUserProfile:
        """Fetch user profile from GitHub API."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

        async with httpx.AsyncClient() as client:
            user_resp = await client.get(self._userinfo_url, headers=headers)
            user_resp.raise_for_status()
            user_data = user_resp.json()

            emails_resp = await client.get(self._emails_url, headers=headers)
            emails_resp.raise_for_status()
            emails_data = emails_resp.json()

        primary_email = self._extract_primary_email(emails_data)

        return OAuthUserProfile(
            provider=OAuthProvider.GITHUB,
            provider_user_id=str(user_data["id"]),
            email=primary_email,
            username=user_data.get("login"),
            display_name=user_data.get("name"),
            raw_profile=user_data,
        )

    @staticmethod
    def _extract_primary_email(emails: list[dict[str, Any]]) -> str | None:
        """Extract primary verified email from GitHub emails response."""
        for email_entry in emails:
            if email_entry.get("primary") and email_entry.get("verified"):
                return email_entry.get("email")
        return None


class GoogleOAuthClient(BaseOAuthClient):
    """Google-specific OAuth client."""

    def __init__(self, settings: GoogleOAuthSettings) -> None:
        """Initialize Google OAuth client.

        Args:
            settings: Google OAuth provider settings.

        """
        super().__init__(
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            authorize_url=settings.authorize_url,
            access_token_url=settings.access_token_url,
            scopes=settings.scopes,
        )
        self._userinfo_url = settings.userinfo_url

    async def fetch_user_profile(self, access_token: str) -> OAuthUserProfile:
        """Fetch user profile from Google API."""
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(self._userinfo_url, headers=headers)
            resp.raise_for_status()
            user_data = resp.json()

        email = user_data.get("email") if user_data.get("email_verified") else None

        return OAuthUserProfile(
            provider=OAuthProvider.GOOGLE,
            provider_user_id=user_data["sub"],
            email=email,
            username=None,
            display_name=user_data.get("name"),
            raw_profile=user_data,
        )


type OAuthClient = GitHubOAuthClient | GoogleOAuthClient


def create_oauth_client(provider: OAuthProvider, settings: OAuthSettings) -> OAuthClient:
    """Create OAuth client for provider. O(1) lookup."""
    provider_settings = settings.get_provider(provider.value)
    if provider_settings is None:
        msg = f"Unknown OAuth provider: {provider}"
        raise ValueError(msg)

    match provider:
        case OAuthProvider.GITHUB:
            return GitHubOAuthClient(cast(GitHubOAuthSettings, provider_settings))
        case OAuthProvider.GOOGLE:
            return GoogleOAuthClient(cast(GoogleOAuthSettings, provider_settings))
        case _ as unreachable:
            assert_never(unreachable)

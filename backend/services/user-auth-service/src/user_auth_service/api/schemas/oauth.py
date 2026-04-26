"""OAuth API schemas for OpenAPI generation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class OAuthProvider(StrEnum):
    """Supported OAuth providers. Frontend uses this enum for type safety."""

    GITHUB = "github"
    GOOGLE = "google"


class OAuthErrorCode(StrEnum):
    """OAuth error codes for frontend i18n error messages."""

    ACCESS_DENIED = "access_denied"
    STATE_MISMATCH = "state_mismatch"
    CODE_EXCHANGE_FAILED = "code_exchange_failed"
    PROFILE_FETCH_FAILED = "profile_fetch_failed"
    ACCOUNT_DISABLED = "account_disabled"
    SERVER_ERROR = "server_error"


class OAuthProviderInfo(BaseModel):
    """Information about an OAuth provider."""

    id: OAuthProvider = Field(description="Provider identifier")
    name: str = Field(description="Display name")
    enabled: bool = Field(description="Whether provider is enabled")


class OAuthProvidersResponse(BaseModel):
    """Response for GET /oauth/providers."""

    providers: list[OAuthProviderInfo] = Field(description="List of available OAuth providers")


class OAuthIdentityResponse(BaseModel):
    """A linked OAuth identity."""

    provider: OAuthProvider = Field(description="OAuth provider")
    provider_username: str | None = Field(description="Username at provider")
    provider_email: str | None = Field(description="Email at provider")
    linked_at: str = Field(description="ISO 8601 datetime when linked")


class OAuthIdentitiesResponse(BaseModel):
    """Response for GET /account/oauth-identities."""

    identities: list[OAuthIdentityResponse] = Field(description="Linked OAuth identities")
    has_password: bool = Field(description="Whether account has a password set")

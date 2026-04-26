"""Configuration management for user-auth-service."""

from __future__ import annotations

from functools import cache
from typing import Literal

from nohiki_core_settings import NohikiBaseSettings
from nohiki_core_settings.env import is_development
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaMixin
from nohiki_redis_utils import CacheTTLConfig, CachingSettings, RateLimitSettings, RedisMixin
from pydantic import BaseModel, Field, PositiveInt, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict


class JWTSettings(BaseModel):
    """JWT authentication settings."""

    private_key_path: str = Field(default="/run/secrets/jwt_private_key.pem")
    key_id: str = Field(default="nohiki-key-1")
    issuer: str = Field(default="https://api.nohiki.com")
    audience: str = Field(default="https://app.nohiki.com")
    access_token_expire_minutes: PositiveInt = Field(default=10)
    refresh_token_expire_days: PositiveInt = Field(default=30)


def _get_default_cookie_name(name: str) -> str:
    """Get cookie name with __Host- prefix only in production (HTTPS required)."""
    if is_development():
        return name
    return f"__Host-{name}"


class CookieSettings(BaseModel):
    """HTTP cookie settings.

    Note: __Host- prefix requires HTTPS and is only used in production.
    In development, plain cookie names are used for HTTP compatibility.
    """

    access_token_name: str = Field(default_factory=lambda: _get_default_cookie_name("nohiki_at"))
    refresh_token_name: str = Field(default_factory=lambda: _get_default_cookie_name("nohiki_rt"))
    oauth_state_name: str = Field(default_factory=lambda: _get_default_cookie_name("nohiki_oauth_state"))
    domain: str | None = Field(default=None)
    secure: bool = Field(default_factory=lambda: not is_development())
    samesite: Literal["lax", "strict", "none"] = Field(default="lax")


class SecuritySettings(BaseModel):
    """CORS and CSRF security settings."""

    cors_allowed_origins: str = Field(
        default="http://localhost:8000,http://localhost:5173,http://localhost:5174,http://localhost:3000"
    )
    csrf_allowed_origins: str = Field(
        default="http://localhost:8000,http://localhost:5173,http://localhost:5174,http://localhost:3000"
    )

    @field_validator("cors_allowed_origins", "csrf_allowed_origins", mode="before")
    @classmethod
    def _parse_origin_list(cls, v: str | list[str]) -> str:
        """Ensure origin lists are stored as comma-separated strings."""
        if isinstance(v, list):
            return ",".join(v)
        return v

    def get_cors_origins(self) -> list[str]:
        """Get CORS allowed origins as a list."""
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def get_csrf_origins(self) -> list[str]:
        """Get CSRF allowed origins as a list."""
        return [o.strip() for o in self.csrf_allowed_origins.split(",") if o.strip()]


class AuthTTLConfig(CacheTTLConfig):
    """Extended TTL config for auth service."""

    # Token blacklist TTL should match max token lifetime (refresh token = 30 days)
    token_blacklist: int = Field(default=2592000, ge=1)


DEV_LOGIN_PER_MINUTE = 1000
DEV_LOGIN_PER_HOUR = 5000
DEV_REGISTER_PER_HOUR = 1000
DEV_REGISTER_PER_DAY = 5000
DEV_RESET_PER_HOUR = 500

PROD_LOGIN_PER_MINUTE = 5
PROD_LOGIN_PER_HOUR = 20
PROD_REGISTER_PER_HOUR = 3
PROD_REGISTER_PER_DAY = 10
PROD_RESET_PER_HOUR = 3


def _env_default(dev_val: int, prod_val: int) -> int:
    """Return dev or prod value based on environment at call time."""
    return dev_val if is_development() else prod_val


class AuthRateLimitConfig(RateLimitSettings):
    """Extended rate limit config for auth service."""

    login_per_minute: int = Field(
        default_factory=lambda: _env_default(DEV_LOGIN_PER_MINUTE, PROD_LOGIN_PER_MINUTE),
        ge=1,
    )
    login_per_hour: int = Field(
        default_factory=lambda: _env_default(DEV_LOGIN_PER_HOUR, PROD_LOGIN_PER_HOUR),
        ge=1,
    )
    register_per_hour: int = Field(
        default_factory=lambda: _env_default(DEV_REGISTER_PER_HOUR, PROD_REGISTER_PER_HOUR),
        ge=1,
    )
    register_per_day: int = Field(
        default_factory=lambda: _env_default(DEV_REGISTER_PER_DAY, PROD_REGISTER_PER_DAY),
        ge=1,
    )
    reset_per_hour: int = Field(
        default_factory=lambda: _env_default(DEV_RESET_PER_HOUR, PROD_RESET_PER_HOUR),
        ge=1,
    )


class AuthCachingSettings(CachingSettings):
    """Extended caching settings for auth service."""

    ttls: AuthTTLConfig = Field(default_factory=AuthTTLConfig)
    rate_limit: AuthRateLimitConfig = Field(default_factory=AuthRateLimitConfig)


class GitHubOAuthSettings(BaseModel):
    """GitHub OAuth provider settings."""

    enabled: bool = Field(default=False)
    client_id: str = Field(default="")
    client_secret: SecretStr = Field(default=SecretStr(""))
    authorize_url: str = Field(default="https://github.com/login/oauth/authorize")
    access_token_url: str = Field(default="https://github.com/login/oauth/access_token")
    userinfo_url: str = Field(default="https://api.github.com/user")
    emails_url: str = Field(default="https://api.github.com/user/emails")
    scopes: tuple[str, ...] = Field(default=("read:user", "user:email"))

    def is_configured(self) -> bool:
        """Check if provider has required credentials configured."""
        return bool(self.client_id and self.client_secret.get_secret_value())


class GoogleOAuthSettings(BaseModel):
    """Google OAuth provider settings."""

    enabled: bool = Field(default=False)
    client_id: str = Field(default="")
    client_secret: SecretStr = Field(default=SecretStr(""))
    authorize_url: str = Field(default="https://accounts.google.com/o/oauth2/v2/auth")
    access_token_url: str = Field(default="https://oauth2.googleapis.com/token")
    userinfo_url: str = Field(default="https://www.googleapis.com/oauth2/v3/userinfo")
    scopes: tuple[str, ...] = Field(default=("openid", "email", "profile"))

    def is_configured(self) -> bool:
        """Check if provider has required credentials configured."""
        return bool(self.client_id and self.client_secret.get_secret_value())


class OAuthSettings(BaseModel):
    """OAuth authentication settings."""

    state_ttl: PositiveInt = Field(default=600)
    callback_base_url: str = Field(default="http://localhost:8000")
    success_redirect_url: str = Field(default="http://localhost:5173/auth/callback")
    error_redirect_url: str = Field(default="http://localhost:5173/auth/callback")
    github: GitHubOAuthSettings = Field(default_factory=GitHubOAuthSettings)
    google: GoogleOAuthSettings = Field(default_factory=GoogleOAuthSettings)

    def get_provider(self, provider: str) -> GitHubOAuthSettings | GoogleOAuthSettings | None:
        """Get provider settings by name. Returns None if unknown provider."""
        providers: dict[str, GitHubOAuthSettings | GoogleOAuthSettings] = {
            "github": self.github,
            "google": self.google,
        }
        return providers.get(provider)

    def get_enabled_providers(self) -> list[str]:
        """Get list of providers that are enabled and configured."""
        enabled: list[str] = []
        if self.github.enabled and self.github.is_configured():
            enabled.append("github")
        if self.google.enabled and self.google.is_configured():
            enabled.append("google")
        return enabled


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, NohikiBaseSettings):
    """User auth service settings."""

    model_config = SettingsConfigDict(env_prefix="USER_AUTH_")

    service_name: str = "user-auth-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Identity Service"
    service_desc_friendly: str = "Authentication, JWT management, and user identity for Nohiki platform"

    trusted_proxy_cidrs: tuple[str, ...] = ()
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    cookie: CookieSettings = Field(default_factory=CookieSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    caching: AuthCachingSettings = Field(default_factory=AuthCachingSettings)
    oauth: OAuthSettings = Field(default_factory=OAuthSettings)


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()

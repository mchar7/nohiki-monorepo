"""Pydantic schemas for user-auth-service REST API."""

from user_auth_service.api.schemas.account import (
    CreateUserRequest,
    UpdateUserRequest,
    UserCreateResponse,
    UserResponse,
)
from user_auth_service.api.schemas.auth import LoginRequest, LoginResponse
from user_auth_service.api.schemas.common import StrictBaseModel
from user_auth_service.api.schemas.oauth import (
    OAuthErrorCode,
    OAuthIdentitiesResponse,
    OAuthIdentityResponse,
    OAuthProvider,
    OAuthProviderInfo,
    OAuthProvidersResponse,
)

__all__ = [
    "CreateUserRequest",
    "LoginRequest",
    "LoginResponse",
    "OAuthErrorCode",
    "OAuthIdentitiesResponse",
    "OAuthIdentityResponse",
    "OAuthProvider",
    "OAuthProviderInfo",
    "OAuthProvidersResponse",
    "StrictBaseModel",
    "UpdateUserRequest",
    "UserCreateResponse",
    "UserResponse",
]

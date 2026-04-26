"""Authentication schemas for user-auth-service."""

from pydantic import BaseModel, EmailStr, Field, SecretStr

from user_auth_service.api.schemas.common import StrictBaseModel


class LoginRequest(StrictBaseModel):
    """Request data for user login."""

    email: EmailStr = Field(..., description="Account email address")
    password: SecretStr = Field(..., min_length=1, description="Account password")


class LoginResponse(BaseModel):
    """Response data for successful login (cookie-based auth).

    Note: Tokens are set via HttpOnly cookies, NOT returned in response body.
    This response only contains user metadata.
    """

    user_id: str
    email: str
    display_name: str | None = None

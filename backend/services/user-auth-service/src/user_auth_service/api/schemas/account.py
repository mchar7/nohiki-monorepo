"""Account management schemas for user-auth-service."""

import unicodedata
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, WithJsonSchema, field_validator

from user_auth_service.api.schemas.common import StrictBaseModel

_CONTROL_CHARACTER_ERROR = "Display name must not contain control characters"
_NULL_DISPLAY_NAME_ERROR = "Display name must not be null"


def _normalize_display_name(value: object) -> object:
    """Normalize Unicode whitespace while rejecting control characters."""
    if not isinstance(value, str):
        return value
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(_CONTROL_CHARACTER_ERROR)
    return " ".join(value.split())


class CreateUserRequest(BaseModel):
    """Request data for creating a user."""

    model_config = {
        "validate_assignment": True,
        "str_strip_whitespace": True,
        "extra": "forbid",
    }

    email: EmailStr = Field(..., description="Valid email address")
    password: SecretStr = Field(..., min_length=8, max_length=128, description="Strong password")
    display_name: str = Field(..., min_length=1, max_length=255, description="Display name")

    _normalize_name = field_validator("display_name", mode="before")(_normalize_display_name)


class UpdateUserRequest(StrictBaseModel):
    """Request data for updating a user."""

    email: EmailStr | None = Field(None, description="Valid email address")
    display_name: Annotated[
        str | None,
        WithJsonSchema(
            {
                "type": "string",
                "minLength": 1,
                "maxLength": 255,
                "description": "Display name",
            }
        ),
    ] = Field(None, min_length=1, max_length=255, description="Display name")
    first_name: str | None = Field(None, min_length=1, max_length=50, description="First name")
    last_name: str | None = Field(None, min_length=1, max_length=50, description="Last name")

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        """Normalize a supplied display name and reject explicit null."""
        if value is None:
            raise ValueError(_NULL_DISPLAY_NAME_ERROR)
        return _normalize_display_name(value)

    password: SecretStr | None = Field(None, min_length=8, max_length=128, description="New password")


class UserResponse(StrictBaseModel):
    """Response data for user operations."""

    id: UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    display_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreateResponse(BaseModel):
    """Response data for user creation."""

    id: str
    email: str
    message: str

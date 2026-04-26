"""Unit tests for identity_service.api.schemas module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError
from user_auth_service.api.schemas import (
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    UpdateUserRequest,
    UserCreateResponse,
    UserResponse,
)


class TestLoginRequest:
    """Tests for LoginRequest schema."""

    def test_valid_login_request(self) -> None:
        """Creates valid login request."""
        data = LoginRequest(
            email="user@example.com",
            password=SecretStr("password123"),
        )

        assert data.email == "user@example.com"
        assert data.password.get_secret_value() == "password123"

    def test_validates_email_format(self) -> None:
        """Validates email format."""
        with pytest.raises(ValidationError, match="email"):
            LoginRequest(
                email="invalid-email",
                password=SecretStr("password123"),
            )

    def test_requires_password(self) -> None:
        """Requires password field."""
        with pytest.raises(ValidationError, match="Field required"):
            LoginRequest(email="user@example.com")

    def test_strips_whitespace_from_email(self) -> None:
        """Strips whitespace from email."""
        data = LoginRequest(
            email="  user@example.com  ",
            password=SecretStr("password"),
        )
        assert data.email == "user@example.com"


class TestLoginResponse:
    """Tests for LoginResponse schema."""

    def test_creates_login_response(self) -> None:
        """Creates valid login response (cookie-based)."""
        data = LoginResponse(
            user_id="user-123",
            email="user@example.com",
            display_name="User",
        )
        assert data.user_id == "user-123"
        assert data.email == "user@example.com"
        assert data.display_name == "User"


class TestCreateUserRequest:
    """Tests for CreateUserRequest schema."""

    def test_requires_display_name(self) -> None:
        """Registration requires a canonical display name."""
        with pytest.raises(ValidationError, match="display_name"):
            CreateUserRequest(email="new@example.com", password=SecretStr("Password123!"))

    @pytest.mark.parametrize("display_name", [None, "", "   ", "\u00a0\u2003"])
    def test_rejects_null_or_blank_display_name(self, display_name: str | None) -> None:
        """Null and whitespace-only names are invalid."""
        with pytest.raises(ValidationError, match="display_name"):
            CreateUserRequest.model_validate(
                {"email": "new@example.com", "password": "Password123!", "display_name": display_name}
            )

    @pytest.mark.parametrize("display_name", ["Jane\nDoe", "Jane\tDoe", "Jane\0Doe", "Jane\x1fDoe"])
    def test_rejects_control_characters(self, display_name: str) -> None:
        """C0 controls are rejected rather than silently normalized."""
        with pytest.raises(ValidationError, match="control"):
            CreateUserRequest(
                email="new@example.com",
                password=SecretStr("Password123!"),
                display_name=display_name,
            )

    @pytest.mark.parametrize(
        ("raw", "canonical"),
        [
            ("  Jane   Doe  ", "Jane Doe"),
            ("\u00a0李\u2003小龍\u3000", "李 小龍"),
            ("Élodie O\u2019Connor-Smith", "Élodie O\u2019Connor-Smith"),
            ("李", "李"),
        ],
    )
    def test_normalizes_valid_international_display_names(self, raw: str, canonical: str) -> None:
        """Unicode whitespace collapses without restricting international names."""
        data = CreateUserRequest(
            email="new@example.com",
            password=SecretStr("Password123!"),
            display_name=raw,
        )
        assert data.display_name == canonical

    def test_accepts_exact_display_name_maximum(self) -> None:
        data = CreateUserRequest(
            email="new@example.com",
            password=SecretStr("Password123!"),
            display_name="x" * 255,
        )
        assert len(data.display_name) == 255

    def test_rejects_display_name_over_maximum(self) -> None:
        with pytest.raises(ValidationError, match="at most 255"):
            CreateUserRequest(
                email="new@example.com",
                password=SecretStr("Password123!"),
                display_name="x" * 256,
            )

    def test_password_min_length(self) -> None:
        """Validates password minimum length of 8."""
        with pytest.raises(ValidationError, match="at least 8"):
            CreateUserRequest(
                email="user@example.com",
                password=SecretStr("short"),
            )

    def test_password_max_length(self) -> None:
        """Validates password maximum length of 128."""
        with pytest.raises(ValidationError, match="at most 128"):
            CreateUserRequest(
                email="user@example.com",
                password=SecretStr("x" * 129),
            )

    def test_rejects_extra_fields(self) -> None:
        """Rejects unknown fields."""
        with pytest.raises(ValidationError, match="Extra inputs"):
            # Create request with extra field using model_validate to bypass type check
            CreateUserRequest.model_validate(
                {
                    "email": "user@example.com",
                    "password": "Password123!",
                    "unknown_field": "value",
                }
            )


class TestUpdateUserRequest:
    """Tests for UpdateUserRequest schema."""

    def test_all_fields_optional(self) -> None:
        """All fields are optional."""
        data = UpdateUserRequest()

        assert data.email is None
        assert data.first_name is None
        assert data.last_name is None
        assert data.display_name is None
        assert data.password is None

    def test_partial_update(self) -> None:
        """Allows partial updates."""
        data = UpdateUserRequest(
            first_name="Updated",
            display_name="Updated Name",
        )

        assert data.first_name == "Updated"
        assert data.display_name == "Updated Name"
        assert data.email is None

    def test_validates_password_when_provided(self) -> None:
        """Validates password constraints when provided."""
        with pytest.raises(ValidationError, match="at least 8"):
            UpdateUserRequest(password=SecretStr("short"))

    def test_validates_email_when_provided(self) -> None:
        """Validates email format when provided."""
        with pytest.raises(ValidationError, match="email"):
            UpdateUserRequest(email="invalid-email")

    @pytest.mark.parametrize("display_name", [None, "", "  ", "\u00a0\u2003"])
    def test_rejects_explicit_null_or_blank_display_name(self, display_name: str | None) -> None:
        """An explicit unusable name cannot erase the canonical profile name."""
        with pytest.raises(ValidationError, match=r"display_name|Display name"):
            UpdateUserRequest.model_validate({"display_name": display_name})

    def test_normalizes_supplied_display_name(self) -> None:
        data = UpdateUserRequest(display_name="\u00a0Élodie\u2003O\u2019Connor-Smith\u3000")
        assert data.display_name == "Élodie O\u2019Connor-Smith"

    @pytest.mark.parametrize("display_name", ["Jane\nDoe", "Jane\tDoe", "Jane\0Doe"])
    def test_rejects_control_characters_on_update(self, display_name: str) -> None:
        with pytest.raises(ValidationError, match="control"):
            UpdateUserRequest(display_name=display_name)

    def test_omitting_display_name_is_allowed(self) -> None:
        data = UpdateUserRequest(first_name="Updated")
        assert "display_name" not in data.model_fields_set


class TestUserResponse:
    """Tests for UserResponse schema."""

    def test_from_attributes(self) -> None:
        """Can be created from ORM model attributes."""
        user_id = uuid.uuid4()
        now = datetime.now(UTC)

        data = UserResponse(
            id=user_id,
            email="user@example.com",
            first_name="John",
            last_name="Doe",
            display_name="John Doe",
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        assert data.id == user_id
        assert data.email == "user@example.com"
        assert data.is_active is True

    def test_handles_none_optional_fields(self) -> None:
        """Handles None values for optional fields."""
        user_id = uuid.uuid4()
        now = datetime.now(UTC)

        data = UserResponse(
            id=user_id,
            email="user@example.com",
            first_name=None,
            last_name=None,
            display_name=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        assert data.first_name is None
        assert data.last_name is None
        assert data.display_name is None


class TestUserCreateResponse:
    """Tests for UserCreateResponse schema."""

    def test_creates_response(self) -> None:
        """Creates valid user creation response."""
        data = UserCreateResponse(
            id="user-123",
            email="new@example.com",
            message="Account created successfully",
        )

        assert data.id == "user-123"
        assert data.email == "new@example.com"
        assert data.message == "Account created successfully"

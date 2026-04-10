"""Tests for nohiki_test_utils utils.jwt_helpers module."""

from __future__ import annotations

from uuid import uuid4

from nohiki_test_utils.utils.jwt_helpers import (
    create_expired_jwt,
    create_jwt,
    create_user_jwt,
)

_JWT_FIXTURE_SECRET = "jwt-fixture-" + "x" * 24


class TestCreateJwt:
    """Tests for create_jwt function."""

    def test_create_jwt_generates_token(self) -> None:
        """create_jwt generates a valid JWT token."""
        token = create_jwt(
            secret=_JWT_FIXTURE_SECRET,
            sub="test-user-id",
            exp_minutes=60,
        )
        assert token is not None
        assert isinstance(token, str)

    def test_create_jwt_includes_claims(self) -> None:
        """create_jwt includes standard claims in payload."""
        token = create_jwt(
            secret=_JWT_FIXTURE_SECRET,
            sub="test-user-id",
            exp_minutes=60,
            additional_claims={"role": "admin"},
        )
        assert token is not None


class TestCreateExpiredJwt:
    """Tests for create_expired_jwt function."""

    def test_create_expired_jwt_generates_token(self) -> None:
        """create_expired_jwt generates an expired JWT token."""
        token = create_expired_jwt(
            secret=_JWT_FIXTURE_SECRET,
            sub="test-user-id",
        )
        assert token is not None
        assert isinstance(token, str)


class TestCreateUserJwt:
    """Tests for create_user_jwt function."""

    def test_create_user_jwt_generates_token(self) -> None:
        """create_user_jwt generates a user JWT token."""
        user_id = uuid4()
        token = create_user_jwt(
            secret=_JWT_FIXTURE_SECRET,
            user_id=user_id,
            exp_minutes=60,
        )
        assert token is not None
        assert isinstance(token, str)

    def test_create_user_jwt_includes_user_id(self) -> None:
        """create_user_jwt includes user ID in subject claim."""
        user_id = uuid4()
        token = create_user_jwt(
            secret=_JWT_FIXTURE_SECRET,
            user_id=user_id,
            exp_minutes=60,
            claims={"email": "test@example.com"},
        )
        assert token is not None

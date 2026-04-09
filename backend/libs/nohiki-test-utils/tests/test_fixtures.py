"""Tests for nohiki_test_utils fixtures module."""

from __future__ import annotations

from nohiki_test_utils.fixtures.auth import (
    create_user_token,
    valid_internal_token,
)


class TestCreateUserToken:
    """Tests for create_user_token function."""

    def test_create_user_token_returns_token(self) -> None:
        """create_user_token returns a JWT token string."""
        token = create_user_token("test-user-id")
        assert token is not None
        assert isinstance(token, str)
        assert "." in token  # JWT format: header.payload.signature

    def test_create_user_token_with_additional_claims(self) -> None:
        """create_user_token includes additional claims."""
        token = create_user_token(
            "test-user-id",
            additional_claims={"role": "admin", "email": "test@example.com"},
        )
        assert token is not None
        # Token should be decodable (though signature won't verify in this simple implementation)
        parts = token.split(".")
        assert len(parts) == 3


class TestValidInternalToken:
    """Tests for valid_internal_token constant."""

    def test_valid_internal_token_exists(self) -> None:
        """valid_internal_token is a pre-generated valid token."""
        assert valid_internal_token is not None
        assert isinstance(valid_internal_token, str)
        parts = valid_internal_token.split(".")
        assert len(parts) == 3

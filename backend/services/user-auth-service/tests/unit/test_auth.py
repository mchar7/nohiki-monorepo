"""Unit tests for RS256 JWT implementation."""

from __future__ import annotations

import jwt
import pytest
from user_auth_service.core.jwt_rs256 import JWTConfig, RS256JWTHandler, generate_rsa_keypair

_SESSION_FAMILY_ID = "550e8400-e29b-41d4-a716-446655440000"


class TestRS256JWTHandler:
    """Tests for RS256JWTHandler."""

    @pytest.fixture
    def handler(self) -> RS256JWTHandler:
        """Create an RS256 handler with an ephemeral RSA keypair."""
        private_pem, public_pem = generate_rsa_keypair()
        _ = public_pem

        config = JWTConfig(
            issuer="https://api.nohiki.com",
            audience="https://app.nohiki.com",
            key_id="test-kid",
            access_token_expire_minutes=10,
            refresh_token_expire_days=30,
        )
        return RS256JWTHandler(private_key_pem=private_pem, config=config)

    def test_create_access_token_is_jwt(self, handler: RS256JWTHandler) -> None:
        """Token creation returns a JWT string."""
        token = handler.create_access_token("user-123", session_family_id=_SESSION_FAMILY_ID)
        assert isinstance(token, str)
        assert token.count(".") == 2

    def test_access_token_contains_expected_claims(self, handler: RS256JWTHandler) -> None:
        """Issued token contains standard claims and is verifiable with public key."""
        token = handler.create_access_token(
            "user-456", session_family_id=_SESSION_FAMILY_ID, roles=["user"], permissions=["read"], tenant_id="t-1"
        )
        payload = jwt.decode(
            token,
            handler._public_key,
            algorithms=["RS256"],
            audience=handler.config.audience,
            issuer=handler.config.issuer,
        )

        assert payload["sub"] == "user-456"
        assert payload["aud"] == handler.config.audience
        assert payload["iss"] == handler.config.issuer
        assert payload["roles"] == ["user"]
        assert payload["permissions"] == ["read"]
        assert payload["tenant_id"] == "t-1"
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload

    def test_get_jwks_includes_kid(self, handler: RS256JWTHandler) -> None:
        """JWKS contains the current key with expected kid."""
        jwks = handler.get_jwks()
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1
        assert jwks["keys"][0]["kid"] == handler.config.key_id

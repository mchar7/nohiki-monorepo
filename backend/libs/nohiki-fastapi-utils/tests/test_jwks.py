"""Tests for JWKS-based JWT verification."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from nohiki_fastapi_utils.jwks import (
    JWKSConfig,
    JWKSVerificationError,
    JWKSVerifier,
    JWTClaims,
    get_current_user_claims,
    get_current_user_id_from_cookie,
)
from pydantic import ValidationError as PydanticValidationError


@pytest.fixture(autouse=True)
def _isolate_verifier_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(JWKSVerifier, "_instance", None)


class TestJWKSConfig:
    """Tests for JWKSConfig model."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("cache_ttl_seconds", 0),
            ("cache_ttl_seconds", -1),
            ("algorithm", "HS256"),
        ],
        ids=("zero-cache-ttl", "negative-cache-ttl", "symmetric-algorithm"),
    )
    def test_rejects_unsafe_configuration(self, field: str, value: object) -> None:
        """Invalid cache lifetimes and caller-selected algorithms are rejected at startup."""
        config = {
            "jwks_url": "https://auth.example.com/.well-known/jwks.json",
            "issuer": "https://auth.example.com",
            "audience": "my-app",
            field: value,
        }

        with pytest.raises(PydanticValidationError):
            JWKSConfig.model_validate(config)


class TestJWTClaims:
    """Tests for JWTClaims dataclass."""

    def test_init_minimal(self) -> None:
        """Test JWTClaims with minimal args."""
        claims = JWTClaims(
            sub="user-123",
            iss="https://auth.example.com",
            aud="my-app",
            exp=1234567890,
            iat=1234567800,
            jti="jwt-id-123",
        )
        assert claims.sub == "user-123"
        assert claims.iss == "https://auth.example.com"
        assert claims.aud == "my-app"
        assert claims.exp == 1234567890
        assert claims.iat == 1234567800
        assert claims.jti == "jwt-id-123"
        assert claims.roles == []
        assert claims.permissions == []
        assert claims.tenant_id is None
        assert claims.session_family_id is None

    def test_init_full(self) -> None:
        """Test JWTClaims with all args."""
        claims = JWTClaims(
            sub="user-123",
            iss="https://auth.example.com",
            aud="my-app",
            exp=1234567890,
            iat=1234567800,
            jti="jwt-id-123",
            roles=["admin", "user"],
            permissions=["read", "write"],
            tenant_id="tenant-456",
            session_family_id="family-789",
        )
        assert claims.roles == ["admin", "user"]
        assert claims.permissions == ["read", "write"]
        assert claims.tenant_id == "tenant-456"
        assert claims.session_family_id == "family-789"


class TestJWKSVerificationError:
    """Tests for JWKSVerificationError exception."""

    def test_init(self) -> None:
        """Test JWKSVerificationError initialization."""
        error = JWKSVerificationError("Token expired")
        assert str(error) == "Token expired"


class TestJWKSVerifier:
    """Tests for JWKSVerifier class."""

    def test_init(self) -> None:
        """Test JWKSVerifier initialization."""
        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        with patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class:
            verifier = JWKSVerifier(config)
            assert verifier._config is config
            mock_client_class.assert_called_once()

    def test_verify_token_success(self) -> None:
        """Test successful token verification."""
        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"

        mock_payload = {
            "sub": "user-123",
            "iss": "https://auth.example.com",
            "aud": "my-app",
            "exp": 1234567890,
            "iat": 1234567800,
            "jti": "jwt-id-123",
            "roles": ["user"],
            "permissions": ["read"],
            "tenant_id": "tenant-456",
            "session_family_id": "family-789",
        }

        with (
            patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class,
            patch("nohiki_fastapi_utils.jwks.jwt.decode", return_value=mock_payload),
        ):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_client_class.return_value = mock_client

            verifier = JWKSVerifier(config)
            claims = verifier.verify_token("mock-token")

            assert claims.sub == "user-123"
            assert claims.roles == ["user"]
            assert claims.tenant_id == "tenant-456"
            assert claims.session_family_id == "family-789"

    def test_verify_token_invalid(self) -> None:
        """Test token verification with invalid token."""
        import jwt as jwt_lib

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"

        with (
            patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class,
            patch(
                "nohiki_fastapi_utils.jwks.jwt.decode",
                side_effect=jwt_lib.InvalidTokenError("Invalid token"),
            ),
        ):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_client_class.return_value = mock_client

            verifier = JWKSVerifier(config)

            with pytest.raises(JWKSVerificationError):
                verifier.verify_token("invalid-token")

    def test_verify_token_expired(self) -> None:
        """Test token verification with expired token."""
        import jwt as jwt_lib

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"

        with (
            patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class,
            patch(
                "nohiki_fastapi_utils.jwks.jwt.decode",
                side_effect=jwt_lib.ExpiredSignatureError("Token expired"),
            ),
        ):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_client_class.return_value = mock_client

            verifier = JWKSVerifier(config)

            with pytest.raises(JWKSVerificationError):
                verifier.verify_token("expired-token")

    def test_verify_token_jwks_error(self) -> None:
        """Test token verification with JWKS fetch error."""
        from jwt.exceptions import PyJWKClientError

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        with patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.side_effect = PyJWKClientError("Failed to fetch JWKS")
            mock_client_class.return_value = mock_client

            verifier = JWKSVerifier(config)

            with pytest.raises(JWKSVerificationError):
                verifier.verify_token("some-token")

    def test_verify_token_issuer_error(self) -> None:
        """Test token verification with invalid issuer."""
        import jwt as jwt_lib

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"

        with (
            patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class,
            patch(
                "nohiki_fastapi_utils.jwks.jwt.decode",
                side_effect=jwt_lib.InvalidIssuerError("Invalid issuer"),
            ),
        ):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_client_class.return_value = mock_client

            verifier = JWKSVerifier(config)

            with pytest.raises(JWKSVerificationError, match="issuer"):
                verifier.verify_token("invalid-issuer-token")

    def test_verify_token_audience_error(self) -> None:
        """Test token verification with invalid audience."""
        import jwt as jwt_lib

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        mock_signing_key = MagicMock()
        mock_signing_key.key = "mock-key"

        with (
            patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class,
            patch(
                "nohiki_fastapi_utils.jwks.jwt.decode",
                side_effect=jwt_lib.InvalidAudienceError("Invalid audience"),
            ),
        ):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
            mock_client_class.return_value = mock_client

            verifier = JWKSVerifier(config)

            with pytest.raises(JWKSVerificationError, match="audience"):
                verifier.verify_token("invalid-audience-token")

    def test_get_token_from_cookie(self) -> None:
        """Test get_token_from_cookie method."""
        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
            cookie_name="test_cookie",
        )

        with patch("nohiki_fastapi_utils.jwks.PyJWKClient"):
            verifier = JWKSVerifier(config)

            request = MagicMock()
            request.cookies = {"test_cookie": "token-value"}

            result = verifier.get_token_from_cookie(request)
            assert result == "token-value"

    def test_get_token_from_cookie_missing(self) -> None:
        """Test get_token_from_cookie when cookie is missing."""
        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        with patch("nohiki_fastapi_utils.jwks.PyJWKClient"):
            verifier = JWKSVerifier(config)

            request = MagicMock()
            request.cookies = {}

            result = verifier.get_token_from_cookie(request)
            assert result is None

    def test_verify_request_missing_token(self) -> None:
        """Test verify_request when token is missing."""
        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        with patch("nohiki_fastapi_utils.jwks.PyJWKClient"):
            verifier = JWKSVerifier(config)

            request = MagicMock()
            request.cookies = {}

            with pytest.raises(JWKSVerificationError, match="cookie not found"):
                verifier.verify_request(request)


class TestGlobalVerifier:
    """Tests for global verifier functions."""

    def test_init_and_get_verifier(self) -> None:
        """Test init_jwks_verifier and get_jwks_verifier."""
        from nohiki_fastapi_utils.jwks import (
            get_jwks_verifier,
            init_jwks_verifier,
        )

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )

        with patch("nohiki_fastapi_utils.jwks.PyJWKClient"):
            verifier = init_jwks_verifier(config)
            assert verifier is not None

            retrieved = get_jwks_verifier()
            assert retrieved is verifier

    def test_get_verifier_returns_instance(self) -> None:
        """Test get_jwks_verifier returns the independently initialized instance."""
        from nohiki_fastapi_utils.jwks import get_jwks_verifier, init_jwks_verifier

        config = JWKSConfig(
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            issuer="https://auth.example.com",
            audience="my-app",
        )
        with patch("nohiki_fastapi_utils.jwks.PyJWKClient"):
            verifier = init_jwks_verifier(config)

        assert get_jwks_verifier() is verifier
        assert isinstance(verifier, JWKSVerifier)


class TestFastAPIDependencies:
    """Tests for FastAPI dependency functions."""

    @pytest.mark.parametrize(
        "dependency",
        [get_current_user_id_from_cookie, get_current_user_claims],
        ids=("user-id", "claims"),
    )
    def test_verification_failures_return_generic_401(self, dependency: Callable[..., object]) -> None:
        """JWT dependency failures never disclose verifier diagnostics to HTTP clients."""
        secret = "JWKS fetch failed for internal-auth:8443 with kid=private-key"
        mock_verifier = MagicMock()
        mock_verifier.verify_request.side_effect = JWKSVerificationError(secret)
        app = FastAPI()

        @app.get("/protected", dependencies=[Depends(dependency)])
        async def protected() -> dict[str, str]:
            return {"status": "ok"}

        with patch("nohiki_fastapi_utils.jwks.get_jwks_verifier", return_value=mock_verifier):
            response = TestClient(app).get("/protected")

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or expired access token"}
        assert secret not in response.text

    def test_get_current_user_id_from_cookie_success(self) -> None:
        """Test get_current_user_id_from_cookie with valid token."""
        from nohiki_fastapi_utils.jwks import get_current_user_id_from_cookie

        mock_claims = JWTClaims(
            sub="550e8400-e29b-41d4-a716-446655440000",
            iss="https://auth.example.com",
            aud="my-app",
            exp=1234567890,
            iat=1234567800,
            jti="jwt-id-123",
        )

        mock_verifier = MagicMock()
        mock_verifier.verify_request.return_value = mock_claims

        with patch("nohiki_fastapi_utils.jwks.get_jwks_verifier", return_value=mock_verifier):
            request = MagicMock()
            result = get_current_user_id_from_cookie(request)
            assert str(result) == "550e8400-e29b-41d4-a716-446655440000"

    def test_get_current_user_id_from_cookie_verification_error(self) -> None:
        """Test get_current_user_id_from_cookie with verification error."""
        from fastapi import HTTPException
        from nohiki_fastapi_utils.jwks import get_current_user_id_from_cookie

        mock_verifier = MagicMock()
        mock_verifier.verify_request.side_effect = JWKSVerificationError("Token expired")

        with patch("nohiki_fastapi_utils.jwks.get_jwks_verifier", return_value=mock_verifier):
            request = MagicMock()
            with pytest.raises(HTTPException) as exc_info:
                get_current_user_id_from_cookie(request)
            assert exc_info.value.status_code == 401

    def test_get_current_user_id_from_cookie_invalid_uuid(self) -> None:
        """Test get_current_user_id_from_cookie with invalid UUID in token."""
        from fastapi import HTTPException
        from nohiki_fastapi_utils.jwks import get_current_user_id_from_cookie

        mock_claims = JWTClaims(
            sub="not-a-valid-uuid",
            iss="https://auth.example.com",
            aud="my-app",
            exp=1234567890,
            iat=1234567800,
            jti="jwt-id-123",
        )

        mock_verifier = MagicMock()
        mock_verifier.verify_request.return_value = mock_claims

        with patch("nohiki_fastapi_utils.jwks.get_jwks_verifier", return_value=mock_verifier):
            request = MagicMock()
            with pytest.raises(HTTPException) as exc_info:
                get_current_user_id_from_cookie(request)
            assert exc_info.value.status_code == 401
            assert "Invalid user ID" in exc_info.value.detail

    def test_get_current_user_claims_success(self) -> None:
        """Test get_current_user_claims with valid token."""
        from nohiki_fastapi_utils.jwks import get_current_user_claims

        mock_claims = JWTClaims(
            sub="user-123",
            iss="https://auth.example.com",
            aud="my-app",
            exp=1234567890,
            iat=1234567800,
            jti="jwt-id-123",
            roles=["admin"],
        )

        mock_verifier = MagicMock()
        mock_verifier.verify_request.return_value = mock_claims

        with patch("nohiki_fastapi_utils.jwks.get_jwks_verifier", return_value=mock_verifier):
            request = MagicMock()
            result = get_current_user_claims(request)
            assert result.sub == "user-123"
            assert result.roles == ["admin"]

    def test_get_current_user_claims_verification_error(self) -> None:
        """Test get_current_user_claims with verification error."""
        from fastapi import HTTPException
        from nohiki_fastapi_utils.jwks import get_current_user_claims

        mock_verifier = MagicMock()
        mock_verifier.verify_request.side_effect = JWKSVerificationError("Token expired")

        with patch("nohiki_fastapi_utils.jwks.get_jwks_verifier", return_value=mock_verifier):
            request = MagicMock()
            with pytest.raises(HTTPException) as exc_info:
                get_current_user_claims(request)
            assert exc_info.value.status_code == 401


class TestJWKSVerifierNotInitialized:
    """Tests for JWKSVerifier when not initialized."""

    def test_raises_runtime_error_when_not_initialized(self) -> None:
        """JWKSVerifier() raises RuntimeError if never configured."""
        JWKSVerifier._instance = None
        with pytest.raises(RuntimeError, match="not initialized"):
            JWKSVerifier()

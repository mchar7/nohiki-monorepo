"""Unit tests for jwt_rs256 module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import dsa, rsa
from user_auth_service.core.jwt_rs256 import (
    JWTConfig,
    RS256JWTHandler,
    generate_rsa_keypair,
    get_jwt_handler,
    init_jwt_handler,
    load_private_key_from_file,
)


@pytest.fixture
def jwt_config() -> JWTConfig:
    """Create a test JWT configuration."""
    return JWTConfig(
        issuer="test-issuer",
        audience="test-audience",
        key_id="test-key-id",
        access_token_expire_minutes=15,
        refresh_token_expire_days=30,
    )


@pytest.fixture(scope="module")
def private_key_pem() -> str:
    """Generate one immutable test RSA private key for this module."""
    private_pem, _ = generate_rsa_keypair()
    return private_pem


@pytest.fixture
def jwt_handler(private_key_pem: str, jwt_config: JWTConfig) -> RS256JWTHandler:
    """Create a test JWT handler."""
    return RS256JWTHandler(private_key_pem, jwt_config)


class TestRS256JWTHandler:
    """Tests for RS256JWTHandler class."""

    def test_init_loads_private_key(self, private_key_pem: str, jwt_config: JWTConfig) -> None:
        """Test that initialization loads the private key."""
        handler = RS256JWTHandler(private_key_pem, jwt_config)

        assert handler._private_key is not None
        assert handler._public_key is not None
        assert handler._config == jwt_config

    def test_init_rejects_non_rsa_key(self, jwt_config: JWTConfig) -> None:
        """Test that initialization rejects non-RSA keys."""
        # Generate a DSA key (not RSA)
        from cryptography.hazmat.primitives import serialization

        dsa_key = dsa.generate_private_key(key_size=2048)
        dsa_pem = dsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        with pytest.raises(TypeError, match="Expected RSA private key"):
            RS256JWTHandler(dsa_pem, jwt_config)

    def test_init_rejects_weak_rsa_key(self, jwt_config: JWTConfig) -> None:
        """Signing keys below 2048 bits are rejected before token issuance."""
        from cryptography.hazmat.primitives import serialization

        weak_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)  # noqa: S505  # rejection fixture
        weak_pem = weak_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        with pytest.raises(ValueError, match="at least 2048 bits"):
            RS256JWTHandler(weak_pem, jwt_config)

    def test_create_access_token_basic(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating a basic access token."""
        user_id = "test-user-123"

        token = jwt_handler.create_access_token(user_id)

        assert token is not None
        assert isinstance(token, str)

        # Decode and verify the token
        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        assert decoded["sub"] == user_id
        assert decoded["iss"] == "test-issuer"
        assert decoded["aud"] == "test-audience"
        assert "iat" in decoded
        assert "exp" in decoded
        assert "jti" in decoded

    def test_create_access_token_with_session_family(self, jwt_handler: RS256JWTHandler) -> None:
        session_family_id = "550e8400-e29b-41d4-a716-446655440000"

        token = jwt_handler.create_access_token("test-user-123", session_family_id=session_family_id)

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )
        assert decoded["session_family_id"] == session_family_id

    def test_create_access_token_without_session_family_remains_compatible(self, jwt_handler: RS256JWTHandler) -> None:
        token = jwt_handler.create_access_token("test-user-123")

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )
        assert "session_family_id" not in decoded

    def test_create_access_token_with_roles(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating access token with roles."""
        user_id = "test-user-123"
        roles = ["admin", "user"]

        token = jwt_handler.create_access_token(user_id, roles=roles)

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        assert decoded["roles"] == roles

    def test_create_access_token_with_permissions(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating access token with permissions."""
        user_id = "test-user-123"
        permissions = ["read:users", "write:users"]

        token = jwt_handler.create_access_token(user_id, permissions=permissions)

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        assert decoded["permissions"] == permissions

    def test_create_access_token_with_tenant_id(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating access token with tenant_id."""
        user_id = "test-user-123"
        tenant_id = "tenant-456"

        token = jwt_handler.create_access_token(user_id, tenant_id=tenant_id)

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        assert decoded["tenant_id"] == tenant_id

    def test_create_access_token_with_all_optional_fields(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating access token with all optional fields."""
        user_id = "test-user-123"
        roles = ["admin"]
        permissions = ["read:all"]
        tenant_id = "tenant-456"

        token = jwt_handler.create_access_token(
            user_id,
            roles=roles,
            permissions=permissions,
            tenant_id=tenant_id,
        )

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        assert decoded["sub"] == user_id
        assert decoded["roles"] == roles
        assert decoded["permissions"] == permissions
        assert decoded["tenant_id"] == tenant_id

    def test_create_access_token_includes_kid_header(self, jwt_handler: RS256JWTHandler) -> None:
        """Test that created tokens include kid header."""
        user_id = "test-user-123"

        token = jwt_handler.create_access_token(user_id)

        # Verify signature and retrieve header in a single verified call
        decoded = jwt.decode_complete(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            options={"require": ["exp", "iat", "sub"]},
        )
        header = decoded["header"]

        assert header["kid"] == "test-key-id"
        assert header["alg"] == "RS256"

    def test_get_jwks_basic(self, jwt_handler: RS256JWTHandler) -> None:
        """Test getting JWKS payload."""
        jwks = jwt_handler.get_jwks()

        assert "keys" in jwks
        assert len(jwks["keys"]) == 1

        key = jwks["keys"][0]
        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert key["kid"] == "test-key-id"
        assert "n" in key  # Modulus
        assert "e" in key  # Exponent

    def test_get_jwks_with_previous_keys(self, jwt_handler: RS256JWTHandler) -> None:
        """Test getting JWKS with previous keys included."""
        previous_keys = [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "old-key-id",
                "n": "old-modulus",
                "e": "AQAB",
            }
        ]

        jwks = jwt_handler.get_jwks(include_previous_keys=previous_keys)

        assert "keys" in jwks
        assert len(jwks["keys"]) == 2

        # Current key should be first
        assert jwks["keys"][0]["kid"] == "test-key-id"
        # Previous key should be second
        assert jwks["keys"][1]["kid"] == "old-key-id"

    def test_config_property(self, jwt_handler: RS256JWTHandler, jwt_config: JWTConfig) -> None:
        """Test config property returns the configuration."""
        assert jwt_handler.config == jwt_config

    def test_verify_access_token_returns_user_id(self, jwt_handler: RS256JWTHandler) -> None:
        """Returns the sub claim for a valid token."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        token = jwt_handler.create_access_token(user_id)

        result = jwt_handler.verify_access_token(token)

        assert result == user_id

    def test_verify_access_token_raises_for_tampered_token(self, jwt_handler: RS256JWTHandler) -> None:
        """Raises InvalidTokenError for a tampered token."""
        token = jwt_handler.create_access_token("user-123")
        tampered = token[:-4] + "XXXX"

        with pytest.raises(jwt.InvalidTokenError):
            jwt_handler.verify_access_token(tampered)

    def test_verify_access_token_raises_for_wrong_audience(self, private_key_pem: str) -> None:
        """Raises InvalidTokenError when audience does not match."""
        verifier = RS256JWTHandler(
            private_key_pem,
            JWTConfig(issuer="test-issuer", audience="expected-audience", key_id="test-key-id"),
        )
        signer = RS256JWTHandler(
            private_key_pem,
            JWTConfig(issuer="test-issuer", audience="other-audience", key_id="test-key-id"),
        )
        token = signer.create_access_token("user-123")

        with pytest.raises(jwt.InvalidTokenError):
            verifier.verify_access_token(token)


class TestLoadPrivateKeyFromFile:
    """Tests for load_private_key_from_file function."""

    def test_load_private_key_from_file_success(self, private_key_pem: str) -> None:
        """Test loading private key from file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(private_key_pem)
            f.flush()
            temp_path = Path(f.name)

        try:
            loaded_pem = load_private_key_from_file(temp_path)
            assert loaded_pem == private_key_pem
            assert "-----BEGIN" in loaded_pem
        finally:
            temp_path.unlink()

    def test_load_private_key_from_file_not_found(self) -> None:
        """Test loading private key from non-existent file."""
        with pytest.raises(FileNotFoundError, match="JWT private key file not found"):
            load_private_key_from_file("/nonexistent/path/key.pem")

    def test_load_private_key_from_file_invalid_pem(self) -> None:
        """Test loading invalid PEM file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write("This is not a PEM file")
            f.flush()
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Invalid PEM format"):
                load_private_key_from_file(temp_path)
        finally:
            temp_path.unlink()


class TestGenerateRSAKeypair:
    """Tests for generate_rsa_keypair function."""

    def test_generate_rsa_keypair_custom_size(self) -> None:
        """Test generating RSA keypair with custom size."""
        private_pem, public_pem = generate_rsa_keypair(key_size=4096)

        assert "-----BEGIN PRIVATE KEY-----" in private_pem
        assert "-----BEGIN PUBLIC KEY-----" in public_pem

        # Verify the key can be loaded and used
        handler = RS256JWTHandler(
            private_pem,
            JWTConfig(
                issuer="test",
                audience="test",
                key_id="test",
            ),
        )
        token = handler.create_access_token("user-123")
        assert token is not None


class TestSingletonManagement:
    """Tests for singleton instance management."""

    def test_init_jwt_handler(self, private_key_pem: str, jwt_config: JWTConfig) -> None:
        """Test initializing the global JWT handler."""
        handler = init_jwt_handler(private_key_pem, jwt_config)

        assert handler is not None
        assert isinstance(handler, RS256JWTHandler)

    def test_get_jwt_handler_when_initialized(self, private_key_pem: str, jwt_config: JWTConfig) -> None:
        """Test getting JWT handler when initialized."""
        init_jwt_handler(private_key_pem, jwt_config)
        handler = get_jwt_handler()

        assert handler is not None
        assert isinstance(handler, RS256JWTHandler)

    def test_get_jwt_handler_when_not_initialized(self) -> None:
        """Test getting JWT handler when not initialized."""
        # Reset the global handler
        with (
            patch("user_auth_service.core.jwt_rs256._JWTHandlerHolder.instance", None),
            pytest.raises(RuntimeError, match="JWT handler not initialized"),
        ):
            get_jwt_handler()

    def test_init_jwt_handler_returns_singleton(self, private_key_pem: str, jwt_config: JWTConfig) -> None:
        """Test that init_jwt_handler returns the same instance."""
        handler1 = init_jwt_handler(private_key_pem, jwt_config)
        handler2 = get_jwt_handler()

        assert handler1 is handler2


class TestJWTEdgeCases:
    """Tests for JWT edge cases and error handling."""

    def test_token_with_empty_roles_list(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating token with empty roles list."""
        user_id = "test-user-123"

        # Empty list should not include roles in payload
        token = jwt_handler.create_access_token(user_id, roles=[])

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        # Empty list is falsy, so roles should not be in payload
        assert "roles" not in decoded

    def test_token_with_empty_permissions_list(self, jwt_handler: RS256JWTHandler) -> None:
        """Test creating token with empty permissions list."""
        user_id = "test-user-123"

        # Empty list should not include permissions in payload
        token = jwt_handler.create_access_token(user_id, permissions=[])

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        # Empty list is falsy, so permissions should not be in payload
        assert "permissions" not in decoded

    def test_token_expiration_time_is_set(self, jwt_handler: RS256JWTHandler) -> None:
        """Test that token expiration time is correctly set."""
        user_id = "test-user-123"
        token = jwt_handler.create_access_token(user_id)

        decoded = jwt.decode(
            token,
            jwt_handler._public_key,
            algorithms=["RS256"],
            audience="test-audience",
            issuer="test-issuer",
        )

        # Expiration should be roughly 15 minutes from now (configured in fixture)
        exp_time = decoded["exp"]
        iat_time = decoded["iat"]
        diff_minutes = (exp_time - iat_time) / 60

        assert 14 <= diff_minutes <= 16  # Allow some tolerance

    def test_jwks_modulus_and_exponent_are_base64url_encoded(self, jwt_handler: RS256JWTHandler) -> None:
        """Test that JWKS modulus and exponent are base64url encoded."""
        import re

        jwks = jwt_handler.get_jwks()
        key = jwks["keys"][0]

        # Base64url should only contain A-Z, a-z, 0-9, -, _ (no padding)
        base64url_pattern = re.compile(r"^[A-Za-z0-9_-]+$")

        assert base64url_pattern.match(key["n"])
        assert base64url_pattern.match(key["e"])

    def test_load_private_key_with_string_path(self, private_key_pem: str) -> None:
        """Test loading private key with string path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(private_key_pem)
            f.flush()
            temp_path = f.name

        try:
            # Pass as string, not Path
            loaded_pem = load_private_key_from_file(temp_path)
            assert loaded_pem == private_key_pem
        finally:
            Path(temp_path).unlink()

    def test_load_private_key_with_path_object(self, private_key_pem: str) -> None:
        """Test loading private key with Path object."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(private_key_pem)
            f.flush()
            temp_path = Path(f.name)

        try:
            # Pass as Path object
            loaded_pem = load_private_key_from_file(temp_path)
            assert loaded_pem == private_key_pem
        finally:
            temp_path.unlink()

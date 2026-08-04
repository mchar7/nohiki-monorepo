"""RS256 JWT implementation with JWKS support.

Capabilities:
- RSA key pair loading from PEM files
- RS256 JWT signing (access tokens)
- JWKS endpoint payload generation
- Key rotation support via multiple public keys
"""

from __future__ import annotations

import uuid
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from nohiki_observability import get_logger

logger = get_logger(__name__)

# JWT configuration constants
JWT_ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10
REFRESH_TOKEN_EXPIRE_DAYS = 30
MIN_RSA_KEY_SIZE = 2048


@dataclass(frozen=True)
class JWTConfig:
    """Immutable JWT configuration."""

    issuer: str
    audience: str
    key_id: str
    access_token_expire_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES
    refresh_token_expire_days: int = REFRESH_TOKEN_EXPIRE_DAYS


class RS256JWTHandler:
    """Handles RS256 JWT operations.

    This class is responsible for:
    - Loading RSA private key from PEM file
    - Creating RS256-signed access tokens
    - Generating JWKS payload for public key distribution
    """

    def __init__(
        self,
        private_key_pem: str,
        config: JWTConfig,
    ) -> None:
        """Initialize the JWT handler with RSA private key.

        Args:
            private_key_pem: RSA private key in PEM format
            config: JWT configuration (issuer, audience, key_id)

        """
        self._private_key: RSAPrivateKey = self._load_private_key(private_key_pem)
        self._public_key: RSAPublicKey = self._private_key.public_key()
        self._config: JWTConfig = config
        logger.info(
            "RS256 JWT handler initialized",
            key_id=config.key_id,
            issuer=config.issuer,
            audience=config.audience,
        )

    @property
    def public_key(self) -> RSAPublicKey:
        """RSA public key for token verification."""
        return self._public_key

    @staticmethod
    def _load_private_key(pem_content: str) -> RSAPrivateKey:
        """Load RSA private key from PEM string."""
        key = serialization.load_pem_private_key(
            pem_content.encode("utf-8"),
            password=None,
        )
        if not isinstance(key, RSAPrivateKey):
            msg = f"Expected RSA private key, got {type(key).__name__}"
            raise TypeError(msg)
        if key.key_size < MIN_RSA_KEY_SIZE:
            msg = "RSA private key must be at least 2048 bits"
            raise ValueError(msg)
        return key

    def create_access_token(
        self,
        user_id: str,
        *,
        session_family_id: str,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """Create a signed RS256 access token.

        Args:
            user_id: Account's UUID
            roles: Optional list of role names
            permissions: Optional list of permission strings
            tenant_id: Optional tenant UUID for multi-tenancy
            session_family_id: Session family UUID for revocation.

        Returns:
            Signed JWT string

        """
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "iss": self._config.issuer,
            "aud": self._config.audience,
            "sub": user_id,
            "iat": now,
            "exp": now + timedelta(minutes=self._config.access_token_expire_minutes),
            "jti": str(uuid.uuid4()),
        }

        if roles:
            payload["roles"] = roles
        if permissions:
            payload["permissions"] = permissions
        if tenant_id:
            payload["tenant_id"] = tenant_id
        payload["session_family_id"] = session_family_id

        return jwt.encode(
            payload,
            self._private_key,
            algorithm=JWT_ALGORITHM,
            headers={"kid": self._config.key_id},
        )

    def get_jwks(self, include_previous_keys: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Generate JWKS payload for the public key endpoint.

        Args:
            include_previous_keys: Optional list of previous JWK entries for rotation

        Returns:
            JWKS dictionary ready for JSON serialization

        """
        # Extract RSA public key numbers
        public_numbers = self._public_key.public_numbers()

        # Encode as base64url (no padding) per RFC 7517
        def _b64url_uint(value: int, length: int) -> str:
            return urlsafe_b64encode(value.to_bytes(length, byteorder="big")).rstrip(b"=").decode("ascii")

        # RSA modulus and exponent
        n = _b64url_uint(public_numbers.n, (public_numbers.n.bit_length() + 7) // 8)
        e = _b64url_uint(public_numbers.e, (public_numbers.e.bit_length() + 7) // 8)

        current_key = {
            "kty": "RSA",
            "use": "sig",
            "alg": JWT_ALGORITHM,
            "kid": self._config.key_id,
            "n": n,
            "e": e,
        }

        keys = [current_key]
        if include_previous_keys:
            keys.extend(include_previous_keys)

        return {"keys": keys}

    def verify_access_token(self, token: str) -> str:
        """Verify a signed access token and return the user ID from the sub claim.

        Uses the service's own RSA public key for verification, avoiding any
        external JWKS network call.

        Args:
            token: Signed RS256 JWT access token string.

        Returns:
            User ID string extracted from the ``sub`` claim.

        Raises:
            jwt.InvalidTokenError: If the token is invalid, expired, or tampered.

        """
        payload = jwt.decode(
            token,
            self._public_key,
            algorithms=[JWT_ALGORITHM],
            audience=self._config.audience,
            issuer=self._config.issuer,
        )
        return str(payload["sub"])

    @property
    def config(self) -> JWTConfig:
        """Get the JWT configuration."""
        return self._config


def load_private_key_from_file(path: str | Path) -> str:
    """Load RSA private key PEM content from file.

    Args:
        path: Path to the PEM file

    Returns:
        PEM content as string

    Raises:
        FileNotFoundError: If key file doesn't exist
        ValueError: If file content is not valid PEM

    """
    path = Path(path)
    if not path.exists():
        msg = f"JWT private key file not found: {path}"
        raise FileNotFoundError(msg)

    content = path.read_text()
    if "-----BEGIN" not in content:
        msg = f"Invalid PEM format in {path}"
        raise ValueError(msg)

    return content


def generate_rsa_keypair(key_size: int = MIN_RSA_KEY_SIZE) -> tuple[str, str]:
    """Generate an RSA key pair for testing purposes.

    Args:
        key_size: RSA key size in bits (default 2048)

    Returns:
        Tuple of (private_key_pem, public_key_pem) as strings

    """
    private_key: RSAPrivateKey = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
    )

    private_pem: str = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem: str = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    return private_pem, public_pem


class _JWTHandlerHolder:
    """Singleton holder for JWT handler."""

    instance: RS256JWTHandler | None = None


def init_jwt_handler(private_key_pem: str, config: JWTConfig) -> RS256JWTHandler:
    """Initialize the global JWT handler singleton."""
    _JWTHandlerHolder.instance = RS256JWTHandler(private_key_pem, config)
    return _JWTHandlerHolder.instance


def get_jwt_handler() -> RS256JWTHandler:
    """Get the initialized JWT handler singleton."""
    if _JWTHandlerHolder.instance is None:
        msg = "JWT handler not initialized. Call init_jwt_handler() first."
        raise RuntimeError(msg)
    return _JWTHandlerHolder.instance

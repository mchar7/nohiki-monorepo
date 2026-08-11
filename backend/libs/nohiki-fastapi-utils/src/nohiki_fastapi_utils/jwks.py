"""JWKS-based JWT verification for RS256 tokens.

Capabilities:
- JWKS fetching with in-memory caching
- RS256 JWT verification using public keys from JWKS
- Cookie-based token extraction
- FastAPI dependency for authenticated user ID
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Self, cast
from uuid import UUID

import jwt
from fastapi import HTTPException, Request, status
from jwt.exceptions import PyJWKClientError
from jwt.jwks_client import PyJWKClient
from pydantic import BaseModel, Field


class JWKSConfig(BaseModel):
    """Configuration for JWKS-based JWT verification."""

    jwks_url: str
    issuer: str
    audience: str
    # Cookie name for access token
    cookie_name: str = "nohiki_at"
    # Cache TTL in seconds (default 1 hour)
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    # Algorithm is intentionally fixed to prevent unsafe runtime configuration.
    algorithm: Literal["RS256"] = "RS256"


@dataclass(slots=True)
class JWTClaims:
    """Validated JWT claims."""

    sub: str  # Account ID
    iss: str  # Issuer
    aud: str  # Audience
    exp: int  # Expiration timestamp
    iat: int  # Issued at timestamp
    jti: str  # JWT ID
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    session_family_id: str | None = None


class JWKSVerificationError(Exception):
    """Raised when JWT verification fails."""


class JWKSVerifier:
    """Verifies JWTs using public keys from a JWKS endpoint.

    Uses PyJWKClient for JWKS fetching with built-in caching.
    """

    _instance: Self | None = None
    _config: JWKSConfig
    _jwk_client: PyJWKClient

    def __new__(cls, config: JWKSConfig | None = None) -> Self:
        """Singleton pattern to ensure only one verifier exists.

        If config is provided, it initializes (or re-initializes) the instance.
        If config is None, it returns the existing instance.
        """
        if config is not None:
            instance = super().__new__(cls)
            instance._config = config
            instance._jwk_client = PyJWKClient(
                config.jwks_url,
                cache_keys=True,
                lifespan=config.cache_ttl_seconds,
            )
            cls._instance = instance
            return instance

        if cls._instance is None:
            msg = "JWKSVerifier not initialized. Call JWKSVerifier(config) first."
            raise RuntimeError(msg)
        return cast("Self", cls._instance)  # ty: ignore[redundant-cast]  # removing cast causes invalid-return-type; ty bug with Self class variables

    def verify_token(self, token: str) -> JWTClaims:
        """Verify a JWT and return its claims.

        Args:
            token: The JWT string to verify

        Returns:
            Validated JWT claims

        Raises:
            JWKSVerificationError: If verification fails

        """
        try:
            # Get the signing key from JWKS
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)

            # Decode and verify the token
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[self._config.algorithm],
                issuer=self._config.issuer,
                audience=self._config.audience,
                options={
                    "require": ["exp", "iat", "sub", "iss", "aud", "jti"],
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )

            return JWTClaims(
                sub=payload["sub"],
                iss=payload["iss"],
                aud=payload["aud"],
                exp=payload["exp"],
                iat=payload["iat"],
                jti=payload["jti"],
                roles=payload.get("roles", []),
                permissions=payload.get("permissions", []),
                tenant_id=payload.get("tenant_id"),
                session_family_id=payload.get("session_family_id"),
            )

        except PyJWKClientError as e:
            msg = f"Failed to fetch signing key: {e}"
            raise JWKSVerificationError(msg) from e
        except jwt.ExpiredSignatureError as e:
            msg = "Token has expired"
            raise JWKSVerificationError(msg) from e
        except jwt.InvalidIssuerError as e:
            msg = "Invalid token issuer"
            raise JWKSVerificationError(msg) from e
        except jwt.InvalidAudienceError as e:
            msg = "Invalid token audience"
            raise JWKSVerificationError(msg) from e
        except jwt.InvalidTokenError as e:
            msg = f"Invalid token: {e}"
            raise JWKSVerificationError(msg) from e

    def get_token_from_cookie(self, request: Request) -> str | None:
        """Extract the access token from the request cookie.

        Args:
            request: FastAPI request object

        Returns:
            Token string or None if not present

        """
        return request.cookies.get(self._config.cookie_name)

    def verify_request(self, request: Request) -> JWTClaims:
        """Verify the JWT from the request cookie.

        Args:
            request: FastAPI request object

        Returns:
            Validated JWT claims

        Raises:
            JWKSVerificationError: If token is missing or invalid

        """
        token = self.get_token_from_cookie(request)
        if not token:
            msg = "Access token cookie not found"
            raise JWKSVerificationError(msg)
        return self.verify_token(token)


def get_jwks_verifier() -> JWKSVerifier:
    """Get the initialized JWKS verifier."""
    return JWKSVerifier()


def init_jwks_verifier(config: JWKSConfig) -> JWKSVerifier:
    """Initialize the global JWKS verifier."""
    return JWKSVerifier(config)


def get_current_user_id_from_cookie(request: Request) -> UUID:
    """FastAPI dependency to extract and validate user ID from JWT cookie.

    Usage:
        ```python
        @router.get("/protected")
        async def protected_endpoint(
            user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)]
        ):
            ...
        ```

    Raises:
        HTTPException: 401 if token is missing or invalid

    """
    verifier = get_jwks_verifier()

    try:
        claims = verifier.verify_request(request)
        return UUID(claims.sub)
    except JWKSVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
        ) from e


def get_current_user_claims(request: Request) -> JWTClaims:
    """FastAPI dependency to get full JWT claims.

    Usage:
        ```python
        @router.get("/protected")
        async def protected_endpoint(
            claims: Annotated[JWTClaims, Depends(get_current_user_claims)]
        ):
            if "admin" in claims.roles:
                ...
        ```

    Raises:
        HTTPException: 401 if token is missing or invalid

    """
    verifier = get_jwks_verifier()

    try:
        return verifier.verify_request(request)
    except JWKSVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from e

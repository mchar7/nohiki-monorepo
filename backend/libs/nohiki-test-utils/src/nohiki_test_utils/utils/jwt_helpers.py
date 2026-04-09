"""JWT helper utilities for testing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

import jwt


def create_jwt(
    secret: str,
    sub: str,
    exp_minutes: int = 60,
    algorithm: str = "HS256",
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """Create a JWT token with standard claims."""
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(minutes=exp_minutes),
    }

    if additional_claims:
        payload |= additional_claims

    result = jwt.encode(payload, secret, algorithm=algorithm)
    return result if isinstance(result, str) else result.decode()


def create_expired_jwt(
    secret: str,
    sub: str,
    algorithm: str = "HS256",
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """Create an expired JWT token for testing error cases."""
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),  # Expired 1 hour ago
    }

    if additional_claims:
        payload |= additional_claims

    result = jwt.encode(payload, secret, algorithm=algorithm)
    return result if isinstance(result, str) else result.decode()


def create_user_jwt(
    secret: str,
    user_id: uuid.UUID,
    exp_minutes: int = 60,
    claims: dict[str, Any] | None = None,
) -> str:
    """Create a user JWT token."""
    return create_jwt(
        secret=secret,
        sub=str(user_id),
        exp_minutes=exp_minutes,
        additional_claims=claims,
    )

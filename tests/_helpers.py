"""Shared helpers for the cross-service integration test package."""

from __future__ import annotations

import jwt

TEST_JWT_SECRET = "test-jwt-secret-for-testing-only"  # noqa: S105 - public test-only signing key
JWT_ALGORITHM = "HS256"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


class TestJWTHandler:
    """Encode and decode JWTs with the shared test secret."""

    def encode_jwt(self, payload: dict[str, object]) -> str:
        """Encode ``payload`` with the shared test secret."""
        return jwt.encode(payload, TEST_JWT_SECRET, algorithm=JWT_ALGORITHM)

    def decode_jwt(self, token: str) -> dict[str, object]:
        """Decode ``token`` with the shared test secret."""
        return jwt.decode(token, TEST_JWT_SECRET, algorithms=[JWT_ALGORITHM])

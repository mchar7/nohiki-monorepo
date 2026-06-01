"""Integration tests for shared authentication middleware across services."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import jwt
import pytest
from nohiki_test_utils import create_jwt, create_user_jwt

from tests.conftest import TEST_JWT_SECRET, TEST_USER_ID, TestJWTHandler

if TYPE_CHECKING:
    from httpx import AsyncClient


def _create_user_token(
    user_id: str,
    *,
    expires_minutes: int = 60,
    additional_claims: dict[str, object] | None = None,
) -> str:
    return create_user_jwt(
        secret=TEST_JWT_SECRET,
        user_id=uuid.UUID(user_id),
        exp_minutes=expires_minutes,
        claims=additional_claims,
    )


def _create_internal_token(service: str) -> str:
    return create_jwt(
        secret=TEST_JWT_SECRET,
        sub=service,
        additional_claims={"iss": "nohiki-internal", "role": "internal", "service": service},
    )


@pytest.fixture
async def authenticated_client(
    http_client: AsyncClient,
    jwt_handler: TestJWTHandler,
) -> AsyncGenerator[tuple[AsyncClient, TestJWTHandler]]:
    """Provide an authenticated HTTP client for middleware tests."""
    # This fixture can be expanded to simulate a service with the middleware applied
    return http_client, jwt_handler


@pytest.fixture
def jwt_handler() -> TestJWTHandler:
    """Provide a simple JWT handler backed by test secrets."""
    return TestJWTHandler()


@pytest.mark.integration
@pytest.mark.requires_docker
class TestAuthenticationMiddleware:
    """Test suite for shared authentication middleware usage across services."""

    def test_jwt_token_validation_consistency(self, jwt_handler: TestJWTHandler) -> None:
        """Test that JWT token validation works consistently via the handler."""
        # Test user token validation
        user_token = _create_user_token(TEST_USER_ID)
        decoded = jwt_handler.decode_jwt(user_token)
        assert decoded["sub"] == TEST_USER_ID
        assert "exp" in decoded

        # Test internal service token validation
        internal_token = _create_internal_token("test-service")
        decoded_internal = jwt_handler.decode_jwt(internal_token)
        assert decoded_internal["sub"] == "test-service"
        assert decoded_internal["service"] == "test-service"
        assert decoded_internal["role"] == "internal"
        assert decoded_internal["iss"] == "nohiki-internal"

    def test_token_expiration_handling(self, jwt_handler: TestJWTHandler) -> None:
        """Test that expired tokens are properly rejected by the handler."""
        expired_token = _create_user_token(TEST_USER_ID, expires_minutes=-5)

        with pytest.raises(jwt.ExpiredSignatureError):
            jwt_handler.decode_jwt(expired_token)

    def test_invalid_signature_rejection(self, jwt_handler: TestJWTHandler) -> None:
        """Test that tokens with invalid signatures are rejected."""
        tampered_token = create_jwt(secret="wrong-secret", sub=TEST_USER_ID)

        with pytest.raises(jwt.InvalidSignatureError):
            jwt_handler.decode_jwt(tampered_token)

    def test_malformed_token_handling(self, jwt_handler: TestJWTHandler) -> None:
        """Test that malformed tokens are properly rejected."""
        malformed_tokens = [
            "not.a.jwt",
            "Bearer malformed",
            "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.malformed",
        ]

        for token in malformed_tokens:
            with pytest.raises(jwt.DecodeError):
                jwt_handler.decode_jwt(token)

    def test_service_to_service_authentication(self, jwt_handler: TestJWTHandler) -> None:
        """Test internal service-to-service authentication patterns."""
        services = [
            "user-service",
            "job-scraper-service",
        ]
        service_tokens = {service: _create_internal_token(service) for service in services}

        for service, token in service_tokens.items():
            decoded = jwt_handler.decode_jwt(token)
            assert decoded["sub"] == service
            assert decoded["service"] == service
            assert decoded["role"] == "internal"

        assert len(set(service_tokens.values())) == len(services)

    def test_user_context_extraction(self, jwt_handler: TestJWTHandler) -> None:
        """Test that user context can be properly extracted from tokens."""
        user_context = {
            "user_id": str(uuid.uuid4()),
            "roles": ["admin"],
            "permissions": ["read:all", "write:all"],
        }
        token = _create_user_token(
            user_context["user_id"],
            additional_claims={
                "roles": user_context["roles"],
                "permissions": user_context["permissions"],
            },
        )
        decoded = jwt_handler.decode_jwt(token)
        assert decoded["sub"] == user_context["user_id"]
        assert decoded.get("roles") == user_context["roles"]
        assert decoded.get("permissions") == user_context["permissions"]

    async def test_concurrent_token_validation(self, jwt_handler: TestJWTHandler) -> None:
        """Test that token validation works correctly under concurrent access."""

        async def validate_token(token: str) -> bool:
            try:
                jwt_handler.decode_jwt(token)
            except jwt.ExpiredSignatureError, jwt.InvalidTokenError:
                return False
            else:
                return True

        tokens = [_create_user_token(str(uuid.uuid4())) for _ in range(10)]
        results = await asyncio.gather(*[validate_token(token) for token in tokens])
        assert all(results)

    def test_role_based_access_patterns(self, jwt_handler: TestJWTHandler) -> None:
        """Test role-based access control patterns used across services."""
        role_permissions = {
            "admin": ["read:all", "write:all"],
            "service": ["internal:operations"],
        }

        for role, permissions in role_permissions.items():
            token = _create_user_token(
                TEST_USER_ID,
                additional_claims={"role": role, "permissions": permissions},
            )
            decoded = jwt_handler.decode_jwt(token)
            assert decoded["role"] == role
            assert decoded["permissions"] == permissions

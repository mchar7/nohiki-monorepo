"""Shared authentication fixtures for testing."""

import base64
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest


def _setup_simple_test_environment() -> Path:
    """Create a minimal test environment for services that don't need databases."""
    # Set test mode to skip event loop and other production features
    os.environ["TEST_MODE"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["OTEL_TRACES_EXPORTER"] = "none"
    os.environ["OTEL_METRICS_EXPORTER"] = "none"
    os.environ["OTEL_LOGS_EXPORTER"] = "none"
    os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"

    # Create temporary directory for test secrets
    secrets_dir = Path(tempfile.mkdtemp(prefix="test_secrets_"))

    # Create test secret files (only user JWT, no internal JWT)
    (secrets_dir / "jwt_secret_key").write_text("test-jwt-secret-key-for-user-tokens")

    return secrets_dir


# Set up test environment before any imports that might trigger config loading
_simple_test_secrets_dir = _setup_simple_test_environment()


@pytest.fixture(scope="session", autouse=True)
def setup_test_secrets() -> Path:
    """Provide the test secrets directory for services that don't need database."""
    return _simple_test_secrets_dir


def create_user_token(user_id: str, additional_claims: dict[str, object] | None = None) -> str:
    """Create a basic user JWT for testing purposes."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, object] = {
        "user_id": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,  # 1 hour from now
    }

    if additional_claims:
        payload |= additional_claims

    header_encoded = base64.b64encode(json.dumps(header).encode()).decode().rstrip("=")
    payload_encoded = base64.b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    return f"{header_encoded}.{payload_encoded}.test-signature"


# Pre-generated token for internal service-to-service communication in tests
valid_internal_token = create_user_token(
    "internal-service",
    additional_claims={"service": "test-service", "role": "internal"},
)


@pytest.fixture
def valid_user_token() -> str:
    """Generate a valid user JWT for testing authenticated endpoints."""
    return create_user_token(str(uuid.uuid4()), additional_claims={"username": "testuser"})


@pytest.fixture
def sample_user_headers(valid_user_token: str) -> dict[str, str]:
    """Create headers for user authentication."""
    return {"Authorization": f"Bearer {valid_user_token}"}

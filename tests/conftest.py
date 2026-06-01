"""Shared fixtures for the cross-service integration test package.

Only the JWT helpers and the OpenTelemetry kill-switch live here. Tests get
their containers from ``nohiki_db_utils.testing`` (Postgres) and
``nohiki_redis_utils.testing`` (Redis) via the per-subtree conftests under
``tests/integration/`` and ``tests/api/``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import jwt

# Disable OpenTelemetry completely during tests. Set at module import so any
# observability bootstrap that runs at test-collect time also sees the flags.
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["OTEL_TRACES_EXPORTER"] = "none"
os.environ["OTEL_METRICS_EXPORTER"] = "none"
os.environ["OTEL_LOGS_EXPORTER"] = "none"
os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = "all"

TEST_JWT_SECRET = "test-jwt-secret-for-testing"
JWT_ALGORITHM = "HS256"

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


class TestJWTHandler:
    """Encode and decode JWTs with the shared test secret."""

    def encode_jwt(self, payload: Mapping[str, object]) -> str:
        """Encode ``payload`` with the shared test secret."""
        return jwt.encode(payload, TEST_JWT_SECRET, algorithm=JWT_ALGORITHM)

    def decode_jwt(self, token: str) -> dict[str, object]:
        """Decode ``token`` with the shared test secret."""
        return jwt.decode(token, TEST_JWT_SECRET, algorithms=[JWT_ALGORITHM])

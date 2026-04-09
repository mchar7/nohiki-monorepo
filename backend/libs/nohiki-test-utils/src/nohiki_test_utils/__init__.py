"""Shared testing utilities for Nohiki services.

Cross-cutting test utilities useful across
all services, regardless of their infrastructure dependencies:

- JWT/Auth helpers for authentication testing
- Test environment setup utilities
- Docker daemon availability checks

Infrastructure-specific fixtures live in their respective libraries:
- Redis fixtures: nohiki-redis-utils (testing extra)
- PostgreSQL fixtures: nohiki-db-utils (testing extra)
"""

from __future__ import annotations

from .fixtures.auth import (
    create_user_token,
    sample_user_headers,
    setup_test_secrets,
    valid_internal_token,
    valid_user_token,
)
from .paths import (
    get_repo_root,
    get_test_secrets_dir,
)
from .utils.docker import docker_daemon_available
from .utils.jwt_helpers import create_expired_jwt, create_jwt, create_user_jwt

__all__ = [
    "create_expired_jwt",
    "create_jwt",
    "create_user_jwt",
    "create_user_token",
    "docker_daemon_available",
    "get_repo_root",
    "get_test_secrets_dir",
    "sample_user_headers",
    "setup_test_secrets",
    "valid_internal_token",
    "valid_user_token",
]

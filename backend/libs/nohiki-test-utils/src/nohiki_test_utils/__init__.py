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

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .fixtures.auth import (
        create_user_token,
        sample_user_headers,
        setup_test_secrets,
        valid_internal_token,
        valid_user_token,
    )
    from .paths import get_repo_root, get_test_secrets_dir
    from .utils.docker import docker_daemon_available
    from .utils.jwt_helpers import create_expired_jwt, create_jwt, create_user_jwt

_EXPORT_MODULES = {
    "create_expired_jwt": "nohiki_test_utils.utils.jwt_helpers",
    "create_jwt": "nohiki_test_utils.utils.jwt_helpers",
    "create_user_jwt": "nohiki_test_utils.utils.jwt_helpers",
    "create_user_token": "nohiki_test_utils.fixtures.auth",
    "docker_daemon_available": "nohiki_test_utils.utils.docker",
    "get_repo_root": "nohiki_test_utils.paths",
    "get_test_secrets_dir": "nohiki_test_utils.paths",
    "sample_user_headers": "nohiki_test_utils.fixtures.auth",
    "setup_test_secrets": "nohiki_test_utils.fixtures.auth",
    "valid_internal_token": "nohiki_test_utils.fixtures.auth",
    "valid_user_token": "nohiki_test_utils.fixtures.auth",
}

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


def __getattr__(name: str) -> object:
    """Load a public helper only when first accessed.

    Args:
        name: Exported attribute name.

    Returns:
        The requested helper.

    Raises:
        AttributeError: If name is not a public package export.

    """
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    return cast("object", getattr(import_module(module_name), name))

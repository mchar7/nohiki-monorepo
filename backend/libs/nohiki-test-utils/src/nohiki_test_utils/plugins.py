"""Pytest plugin configuration for nohiki test support."""

from __future__ import annotations

import pytest

from nohiki_test_utils.utils.docker import docker_daemon_available


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "requires_docker: tests that need running containers (testcontainers)")
    config.addinivalue_line("markers", "integration: mark integration tests that test multiple components")
    config.addinivalue_line("markers", "unit: mark unit tests (default)")
    config.addinivalue_line("markers", "slow: mark tests as slow running")


def pytest_collection_modifyitems(_config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked with requires_docker when Docker is unavailable."""
    if docker_daemon_available():
        return

    skip_docker = pytest.mark.skip(reason="Docker daemon not available")
    for item in items:
        if "requires_docker" in item.keywords:
            item.add_marker(skip_docker)


# Register fixture modules as pytest plugins
pytest_plugins = [
    "nohiki_test_utils.fixtures.auth",
    "nohiki_test_utils.fixtures.clients",
]

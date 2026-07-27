"""Pytest plugin configuration for nohiki test support."""

from __future__ import annotations

import os
import shutil
import tempfile
from importlib import import_module
from typing import Protocol, cast

import pytest

_CONTAINER_BACKED_FIXTURES: frozenset[str] = frozenset(
    {
        "async_engine",
        "async_session",
        "async_session_factory",
        "kafka_container",
        "postgres_container",
        "redis_cache",
        "redis_client",
        "redis_container",
    }
)

_FIXTURE_PLUGIN_MODULES = (
    "nohiki_test_utils.fixtures.auth",
    "nohiki_test_utils.fixtures.clients",
)

_EMPTY_SECRETS_DIR_KEY: pytest.StashKey[str] = pytest.StashKey()


class _DockerAvailabilityModule(Protocol):
    def docker_daemon_available(self) -> bool: ...


def _docker_daemon_available() -> bool:
    docker_module = cast("_DockerAvailabilityModule", import_module("nohiki_test_utils.utils.docker"))
    return docker_module.docker_daemon_available()


def pytest_load_initial_conftests(early_config: pytest.Config) -> None:
    """Point file-secret loading at an empty tree for the whole session.

    ``NohikiBaseSettings`` reads ``SECRETS_DIR`` on every construction, and services build
    theirs at module import, so collection alone reads whatever secrets tree the developer
    or deployment mounted and each suite's result then depends on a gitignored directory.
    An empty directory contributes no values while still existing, which the settings
    source requires outside development. This hook runs ahead of conftest import, where
    settings may already be constructed.

    Args:
        early_config: Session configuration, carries the directory to the teardown hook.
    """
    secrets_dir = tempfile.mkdtemp(prefix="nohiki-empty-secrets-")
    early_config.stash[_EMPTY_SECRETS_DIR_KEY] = secrets_dir
    os.environ["SECRETS_DIR"] = secrets_dir


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the empty secrets tree created for the session.

    Args:
        config: Session configuration carrying the directory to remove.
    """
    secrets_dir = config.stash.get(_EMPTY_SECRETS_DIR_KEY, None)
    if secrets_dir is not None:
        shutil.rmtree(secrets_dir, ignore_errors=True)


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "requires_docker: tests that need running containers (testcontainers)")
    config.addinivalue_line("markers", "integration: mark integration tests that test multiple components")
    config.addinivalue_line("markers", "unit: mark unit tests (default)")
    config.addinivalue_line("markers", "slow: mark tests as slow running")

    for plugin_name in _FIXTURE_PLUGIN_MODULES:
        if not config.pluginmanager.hasplugin(plugin_name):
            fixture_plugin = import_module(plugin_name)
            config.pluginmanager.register(fixture_plugin, plugin_name)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Enforce and apply Docker test collection policy."""
    violations: list[str] = []
    for item in items:
        if not isinstance(item, pytest.Function):
            continue
        container_fixtures = _CONTAINER_BACKED_FIXTURES.intersection(item.fixturenames)
        # Explicit markers keep the CI gate visible at each container-backed test site.
        if container_fixtures and "requires_docker" not in item.keywords:
            fixture_names = ", ".join(sorted(container_fixtures))
            violations.append(f"- {item.nodeid} (fixtures: {fixture_names})")

    if violations:
        details = "\n".join(violations)
        message = f"Container-backed tests must be marked with @pytest.mark.requires_docker:\n{details}"
        raise pytest.UsageError(message)

    if _docker_daemon_available():
        return

    skip_docker = pytest.mark.skip(reason="Docker daemon not available")
    for item in items:
        if "requires_docker" in item.keywords:
            item.add_marker(skip_docker)

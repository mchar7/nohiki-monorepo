"""Pytest plugin configuration for nohiki test support."""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import tempfile
from collections.abc import Buffer, Callable, Iterator
from importlib import import_module
from typing import Protocol, cast

import pytest

type _SocketAddress = tuple[object, ...] | str | Buffer | int


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
_NETWORK_ALLOWED_MARKERS: frozenset[str] = frozenset(
    {
        "e2e",
        "integration",
        "requires_docker",
    }
)

# Git exports its repository-discovery variables to hooks, where they override cwd-based
# discovery. A scratch-repo `git init` under a leaked worktree GIT_DIR therefore targets the
# real repository: it re-initializes the shared repo as bare, and the `git add`/`git commit`
# calls that follow rewrite and delete that repository's tracked files. The guard belongs to
# this plugin rather than one package's conftest so every package shelling out to git
# inherits it without declaring a conftest of its own.
_GIT_DISCOVERY_ENV: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


class _OutboundNetworkProhibited(BaseException):
    """Keep blocked calls visible through dependency exception wrappers."""


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


def _network_error(request: pytest.FixtureRequest, call: str, target: object) -> _OutboundNetworkProhibited:
    message = (
        f"Unmocked outbound network in {request.node.nodeid}: socket.{call}({target!r}). "
        "Stub the network-facing function the test depends on at its module boundary. "
        "If the traffic is intentional, mark the test with an integration marker excluded from the unit lane."
    )
    return _OutboundNetworkProhibited(message)


def _is_numeric_host(host: str | bytes | None) -> bool:
    if host is None:
        return True
    try:
        candidate = host.decode("ascii") if isinstance(host, bytes) else host
        ipaddress.ip_address(candidate)
    except UnicodeDecodeError, ValueError:
        return False
    return True


@pytest.fixture(scope="session", autouse=True)
def _scrub_git_discovery_env() -> Iterator[None]:
    """Detach the session from any inherited Git repository discovery.

    SESSION scope is the load-bearing part: a function-scoped scrub would run after
    module-scoped fixtures that shell out to git during setup, which is precisely when the
    damage happens.

    Yields:
        Control for the session, with the discovery variables absent from the environment.
    """
    patch = pytest.MonkeyPatch()
    for name in _GIT_DISCOVERY_ENV:
        patch.delenv(name, raising=False)
    yield
    patch.undo()


def _install_outbound_network_guard(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent an unmarked test from resolving or contacting network peers."""
    if any(request.node.get_closest_marker(marker) is not None for marker in _NETWORK_ALLOWED_MARKERS):
        return

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_getaddrinfo = cast("Callable[..., object]", socket.getaddrinfo)

    def guarded_connect(sock: socket.socket, address: _SocketAddress) -> None:
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            raise _network_error(request, "socket.connect", address)
        original_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: _SocketAddress) -> int:
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            raise _network_error(request, "socket.connect_ex", address)
        return original_connect_ex(sock, address)

    def guarded_sendto(sock: socket.socket, data: Buffer, address: _SocketAddress) -> int:
        if sock.family in {socket.AF_INET, socket.AF_INET6}:
            raise _network_error(request, "socket.sendto", address)
        return original_sendto(sock, data, address)

    def guarded_getaddrinfo(host: str | bytes | None, *args: object, **kwargs: object) -> object:
        if not _is_numeric_host(host):
            raise _network_error(request, "getaddrinfo", host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def _no_outbound_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the outbound network guard for an unmarked test."""
    _install_outbound_network_guard(request, monkeypatch)


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

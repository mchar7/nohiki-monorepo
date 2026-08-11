"""Docker daemon reachability helpers used by test fixtures.

This is intentionally lightweight: it only checks socket reachability for the
Docker endpoint (unix socket or tcp).
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterator
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse


def _can_connect_unix_socket(path: Path) -> bool:
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        sock.connect(str(path))
    except OSError:
        return False
    else:
        return True
    finally:
        if sock is not None:
            sock.close()


def _can_connect_tcp(host: str | None, port: int | None) -> bool:
    if not host or port is None:
        return False
    sock: socket.socket | None = None
    try:
        sock = socket.create_connection((host, port), timeout=0.2)
    except OSError:
        return False
    else:
        return True
    finally:
        if sock is not None:
            sock.close()


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None

    if not isinstance(value, dict):
        return None
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _docker_config_dir() -> Path:
    if docker_config := os.environ.get("DOCKER_CONFIG"):
        return Path(docker_config).expanduser()
    return Path.home() / ".docker"


def _docker_context_host() -> str | None:
    """Read the active Docker CLI context endpoint without invoking the CLI."""
    config_dir = _docker_config_dir()
    context_name = os.environ.get("DOCKER_CONTEXT")
    if context_name is None:
        config = _read_json_object(config_dir / "config.json")
        configured_context = config.get("currentContext") if config is not None else None
        context_name = configured_context if isinstance(configured_context, str) else None

    if not context_name or context_name == "default":
        return None

    context_id = sha256(context_name.encode()).hexdigest()
    metadata = _read_json_object(config_dir / "contexts" / "meta" / context_id / "meta.json")
    endpoints: object = metadata.get("Endpoints") if metadata is not None else None
    if not isinstance(endpoints, dict):
        return None

    docker_endpoint: object = endpoints.get("docker")
    if not isinstance(docker_endpoint, dict):
        return None

    host: object = docker_endpoint.get("Host")
    return host if isinstance(host, str) and host else None


def _docker_endpoint_candidates() -> Iterator[str]:
    """Yield Docker endpoints in documented discovery precedence."""
    seen: set[str] = set()

    if docker_host := os.environ.get("DOCKER_HOST"):
        seen.add(docker_host)
        yield docker_host
        return

    if (context_host := _docker_context_host()) and context_host not in seen:
        seen.add(context_host)
        yield context_host

    if runtime_dir := os.environ.get("XDG_RUNTIME_DIR"):
        for socket_path in (Path(runtime_dir) / "docker.sock", Path(runtime_dir) / "podman" / "podman.sock"):
            endpoint = f"unix://{socket_path}"
            if endpoint not in seen:
                seen.add(endpoint)
                yield endpoint

    fallback = "unix:///var/run/docker.sock"
    if fallback not in seen:
        yield fallback


def _docker_endpoint_available(endpoint: str) -> bool:
    parsed = urlparse(endpoint)

    if parsed.scheme in ("unix", ""):
        path = Path(parsed.path or endpoint.removeprefix("unix://"))
        return path.exists() and _can_connect_unix_socket(path)

    if parsed.scheme == "tcp":
        try:
            port = parsed.port
        except ValueError:
            return False
        return _can_connect_tcp(parsed.hostname, port)

    return False


# Docker availability is a property of the machine, so it is probed once and then inherited. The
# verdict lives in the environment rather than in this module because a nested pytest session may
# re-import the module, and would get a cold cache, but it always inherits the environment. A
# nested session starts inside a test that has installed the outbound-network guard, so a second
# probe there resolves a hostname the guard rejects and kills that session before it collects.
DOCKER_ENDPOINT_VERDICT_ENV = "NOHIKI_TEST_DOCKER_ENDPOINT"


def _probe_docker_endpoint() -> str | None:
    return next((endpoint for endpoint in _docker_endpoint_candidates() if _docker_endpoint_available(endpoint)), None)


def publish_docker_endpoint_verdict() -> str | None:
    """Return the inherited verdict, or probe once and record it for every nested session."""
    verdict = os.environ.get(DOCKER_ENDPOINT_VERDICT_ENV)
    if verdict is not None:
        return verdict or None
    endpoint = _probe_docker_endpoint()
    os.environ[DOCKER_ENDPOINT_VERDICT_ENV] = endpoint or ""
    return endpoint


@lru_cache(maxsize=1)
def resolve_docker_endpoint() -> str | None:
    """Return the Docker endpoint for this machine without probing twice.

    A published session verdict answers without touching the network, which is what keeps
    collection inside a nested pytest session from resolving a hostname the outer test's
    outbound guard forbids. Probing is the fallback for callers outside a pytest session.
    """
    verdict = os.environ.get(DOCKER_ENDPOINT_VERDICT_ENV)
    if verdict is not None:
        return verdict or None
    return _probe_docker_endpoint()


def docker_daemon_available() -> bool:
    """Return True if a discovered Docker daemon endpoint is reachable."""
    return resolve_docker_endpoint() is not None

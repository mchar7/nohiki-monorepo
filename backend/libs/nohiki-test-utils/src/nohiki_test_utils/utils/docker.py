"""Docker daemon reachability helpers used by test fixtures.

This is intentionally lightweight: it only checks socket reachability for the
Docker endpoint (unix socket or tcp).
"""

from __future__ import annotations

import os
import socket
from functools import lru_cache
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


@lru_cache(maxsize=1)
def docker_daemon_available() -> bool:
    """Return True if the Docker daemon endpoint is reachable."""
    docker_host = os.environ.get("DOCKER_HOST") or "unix:///var/run/docker.sock"
    parsed = urlparse(docker_host)

    if parsed.scheme in ("unix", ""):
        path = Path(parsed.path or docker_host.removeprefix("unix://"))
        return path.exists() and _can_connect_unix_socket(path)

    if parsed.scheme == "tcp":
        return _can_connect_tcp(parsed.hostname, parsed.port)

    return False

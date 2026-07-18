#!/usr/bin/env python3
"""Manage the local Gateway port-forward without assuming a controller Service name."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import cast

NAMESPACE = os.environ.get("K8S_NAMESPACE", "nohiki")
GATEWAY = os.environ.get("K8S_GATEWAY", "nohiki-gateway")
HOST = os.environ.get("K8S_GATEWAY_HOST", "nohiki.localhost")
LOCAL_PORT = int(os.environ.get("K8S_GATEWAY_PORT", "8080"))
HTTP_OK = 200
_RUNTIME_ROOT = Path(
    os.environ.get(
        "XDG_RUNTIME_DIR",
        str(Path(tempfile.gettempdir()) / f"nohiki-{os.getuid()}"),
    )
)
STATE_DIR = _RUNTIME_ROOT / "nohiki-k8s"
STATE_FILE = STATE_DIR / "gateway-proxy.json"
LOG_FILE = STATE_DIR / "gateway-proxy.log"

# These aliases mark the sole boundary where commands assembled from validated,
# locally discovered Kubernetes identifiers are allowed to execute.
_RUN_TRUSTED = subprocess.run
_POPEN_TRUSTED = subprocess.Popen

type JSONValue = None | bool | int | float | str | list[JSONValue] | JSONObject
type JSONObject = dict[str, JSONValue]


def _as_object(value: object) -> JSONObject:
    return cast("JSONObject", value) if isinstance(value, dict) else {}


def _as_objects(value: object) -> list[JSONObject]:
    if not isinstance(value, list):
        return []
    return [_as_object(item) for item in value if isinstance(item, dict)]


def _object_at(document: JSONObject, *keys: str) -> JSONObject:
    current = document
    for key in keys:
        current = _as_object(current.get(key))
    return current


def _objects_at(document: JSONObject, *keys: str) -> list[JSONObject]:
    if not keys:
        return []
    return _as_objects(_object_at(document, *keys[:-1]).get(keys[-1]))


def _kubectl_executable() -> str:
    executable = shutil.which("kubectl")
    if executable is None:
        msg = "kubectl executable was not found on PATH"
        raise FileNotFoundError(msg)
    return executable


def _write_stdout(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def _write_stderr(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = STATE_DIR.stat(follow_symlinks=False)
    if STATE_DIR.is_symlink() or details.st_uid != os.getuid() or details.st_mode & 0o077:
        msg = f"managed proxy runtime directory is not private: {STATE_DIR}"
        raise PermissionError(msg)


def kubectl_json(*args: str) -> JSONObject:
    """Run kubectl and return its JSON object response."""
    result = _RUN_TRUSTED(
        [_kubectl_executable(), *args, "-o", "json"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    value = cast("object", json.loads(result.stdout))
    if not isinstance(value, dict):
        msg = "kubectl returned a non-object response"
        raise TypeError(msg)
    return cast("JSONObject", value)


def conditions_ready(conditions: list[JSONObject], required: tuple[str, ...]) -> bool:
    """Return whether every required condition has status ``True``."""
    current = {item.get("type"): item.get("status") for item in conditions}
    return all(current.get(name) == "True" for name in required)


def _matching_route_parents(route: JSONObject) -> list[JSONObject]:
    return [
        parent
        for parent in _objects_at(route, "status", "parents")
        if _object_at(parent, "parentRef").get("name") == GATEWAY
        and _object_at(parent, "parentRef").get("namespace", NAMESPACE) == NAMESPACE
    ]


def require_gateway_ready() -> tuple[JSONObject, set[str]]:
    """Validate Gateway and attached route readiness and return its addresses."""
    gateway = kubectl_json("-n", NAMESPACE, "get", "gateway", GATEWAY)
    conditions = _objects_at(gateway, "status", "conditions")
    if not conditions_ready(conditions, ("Accepted", "Programmed")):
        msg = f"Gateway {NAMESPACE}/{GATEWAY} is not Accepted=True and Programmed=True"
        raise RuntimeError(msg)

    addresses = {
        value
        for item in _objects_at(gateway, "status", "addresses")
        if isinstance((value := item.get("value")), str) and value
    }
    if not addresses:
        msg = f"Gateway {NAMESPACE}/{GATEWAY} has no programmed status address"
        raise RuntimeError(msg)

    attached: list[JSONValue] = []
    routes = _objects_at(kubectl_json("-n", NAMESPACE, "get", "httproute"), "items")
    for route in routes:
        matching = _matching_route_parents(route)
        if matching:
            attached.append(_object_at(route, "metadata").get("name", "<unnamed>"))
        for parent in matching:
            if not conditions_ready(_objects_at(parent, "conditions"), ("Accepted", "ResolvedRefs")):
                route_name = _object_at(route, "metadata").get("name")
                msg = f"HTTPRoute {route_name} is not Accepted=True and ResolvedRefs=True"
                raise RuntimeError(msg)
    if not attached:
        msg = f"Gateway {NAMESPACE}/{GATEWAY} has no attached HTTPRoutes"
        raise RuntimeError(msg)
    return gateway, addresses


def _service_addresses(service: JSONObject) -> set[str]:
    spec = _object_at(service, "spec")
    ingress = _objects_at(service, "status", "loadBalancer", "ingress")
    values: list[JSONValue] = [
        spec.get("clusterIP"),
        *cast("list[JSONValue]", spec.get("clusterIPs", [])),
        *cast("list[JSONValue]", spec.get("externalIPs", [])),
        *(entry.get("ip") for entry in ingress),
        *(entry.get("hostname") for entry in ingress),
    ]
    return {value for value in values if isinstance(value, str) and value}


def _gateway_owns_service(service: JSONObject, gateway_uid: JSONValue) -> bool:
    metadata = _object_at(service, "metadata")
    labels = _object_at(metadata, "labels")
    owned = bool(gateway_uid) and any(
        owner.get("uid") == gateway_uid for owner in _objects_at(metadata, "ownerReferences")
    )
    return owned or labels.get("gateway.networking.k8s.io/gateway-name") == GATEWAY


def _http_service_ports(service: JSONObject) -> list[JSONObject]:
    return [
        port
        for port in _objects_at(service, "spec", "ports")
        if port.get("port") in (80, 8080)
        or port.get("appProtocol") in ("http", "kubernetes.io/h2c")
        or port.get("name") in ("http", "http2")
    ]


def discover_service(gateway: JSONObject, addresses: set[str]) -> tuple[str, str, int]:
    """Resolve the unique Gateway-owned Service matching its status addresses."""
    services = _objects_at(kubectl_json("get", "service", "--all-namespaces"), "items")
    gateway_uid = _object_at(gateway, "metadata").get("uid")
    matches: list[tuple[str, str, int]] = []
    for service in services:
        if not addresses.intersection(_service_addresses(service)):
            continue
        if not _gateway_owns_service(service, gateway_uid):
            continue
        metadata = _object_at(service, "metadata")
        http_ports = _http_service_ports(service)
        if len(http_ports) != 1:
            msg = f"Gateway Service {metadata.get('namespace')}/{metadata.get('name')} has {len(http_ports)} HTTP ports"
            raise RuntimeError(msg)
        namespace = cast("str", metadata["namespace"])
        name = cast("str", metadata["name"])
        remote_port = int(cast("str", http_ports[0]["port"]))
        matches.append((namespace, name, remote_port))
    if len(matches) != 1:
        msg = f"Gateway status and ownership resolve to {len(matches)} Services; expected exactly one"
        raise RuntimeError(msg)
    return matches[0]


def process_alive(pid: int) -> bool:
    """Return whether a process exists and can be signalled."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError, PermissionError:
        return False
    return True


def read_state() -> JSONObject | None:
    """Read the managed proxy state, returning ``None`` when it is absent."""
    try:
        value = cast("object", json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        msg = f"invalid managed proxy state: {exc}"
        raise RuntimeError(msg) from exc
    return cast("JSONObject", value) if isinstance(value, dict) else None


def managed_pid(state: JSONObject) -> int:
    """Validate and return the PID recorded for the managed port-forward."""
    pid = state.get("pid")
    if not isinstance(pid, int) or pid <= 1:
        msg = "managed proxy state contains an invalid PID"
        raise RuntimeError(msg)
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ")
    except OSError as exc:
        msg = f"cannot verify managed proxy PID {pid}: {exc}"
        raise RuntimeError(msg) from exc
    expected = f"port-forward service/{state.get('service', '')}".encode()
    if expected not in command:
        msg = f"refusing to signal PID {pid}: it is not the recorded port-forward"
        raise RuntimeError(msg)
    return pid


def port_open() -> bool:
    """Return whether the configured loopback port accepts connections."""
    try:
        with socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=0.2):
            return True
    except OSError:
        return False


def http_ready() -> bool:
    """Return whether the forwarded Gateway health endpoint is ready."""
    connection = http.client.HTTPConnection("127.0.0.1", LOCAL_PORT, timeout=1)
    try:
        connection.request("GET", "/healthz", headers={"Host": HOST})
        return connection.getresponse().status == HTTP_OK
    except OSError:
        return False
    finally:
        connection.close()


def start() -> None:
    """Start the managed Gateway port-forward and wait for HTTP readiness."""
    state = read_state()
    if state:
        pid = state.get("pid")
        if isinstance(pid, int) and process_alive(pid):
            managed_pid(state)
            if http_ready():
                _write_stdout(f"Gateway proxy already ready at http://{HOST}:{LOCAL_PORT}")
                return
            msg = "managed Gateway proxy is alive but not ready"
            raise RuntimeError(msg)
        STATE_FILE.unlink(missing_ok=True)
    if port_open():
        msg = f"localhost:{LOCAL_PORT} is occupied by an unmanaged process"
        raise RuntimeError(msg)

    gateway, addresses = require_gateway_ready()
    namespace, service, remote_port = discover_service(gateway, addresses)
    _ensure_state_dir()
    with LOG_FILE.open("ab") as log:
        process = _POPEN_TRUSTED(
            [
                _kubectl_executable(),
                "-n",
                namespace,
                "port-forward",
                f"service/{service}",
                f"{LOCAL_PORT}:{remote_port}",
                "--address=127.0.0.1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    STATE_FILE.write_text(
        json.dumps(
            {
                "pid": process.pid,
                "namespace": namespace,
                "service": service,
                "local_port": LOCAL_PORT,
                "host": HOST,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    STATE_FILE.chmod(0o600)
    for _ in range(100):
        if process.poll() is not None:
            STATE_FILE.unlink(missing_ok=True)
            msg = f"kubectl port-forward exited; inspect {LOG_FILE}"
            raise RuntimeError(msg)
        if http_ready():
            _write_stdout(f"Gateway proxy ready at http://{HOST}:{LOCAL_PORT}")
            return
        time.sleep(0.1)
    stop()
    msg = f"Gateway proxy did not become HTTP-ready at http://{HOST}:{LOCAL_PORT}/healthz"
    raise RuntimeError(msg)


def stop() -> None:
    """Stop the managed Gateway port-forward and remove its state file."""
    state = read_state()
    if not state:
        return
    pid = state.get("pid")
    if not isinstance(pid, int) or not process_alive(pid):
        STATE_FILE.unlink(missing_ok=True)
        return
    pid = managed_pid(state)
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not process_alive(pid):
            STATE_FILE.unlink(missing_ok=True)
            return
        time.sleep(0.1)
    msg = f"managed Gateway proxy PID {pid} did not stop"
    raise RuntimeError(msg)


def status() -> None:
    """Validate and report readiness of the managed Gateway port-forward."""
    state = read_state()
    if not state:
        msg = "Gateway proxy is not managed"
        raise RuntimeError(msg)
    pid = managed_pid(state)
    if not process_alive(pid) or not http_ready():
        msg = "Gateway proxy is not ready"
        raise RuntimeError(msg)
    _write_stdout(f"Gateway proxy PID {pid} is ready at http://{HOST}:{LOCAL_PORT}")


def main() -> int:
    """Run the requested Gateway proxy lifecycle action."""
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status"))
    action = parser.parse_args().action
    try:
        {"start": start, "stop": stop, "status": status}[action]()
    except (
        RuntimeError,
        subprocess.CalledProcessError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        _write_stderr(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

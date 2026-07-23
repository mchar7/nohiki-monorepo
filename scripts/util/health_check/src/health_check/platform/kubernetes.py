"""Kubernetes platform implementation using kubectl."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import dataclass
from typing import Final, TypedDict, cast
from urllib.parse import quote, urlsplit

import httpx

from health_check.platform.direct_clients import kafka_command, psql, valkey_info
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class _WaitingState(TypedDict, total=False):
    """Kubernetes container waiting state."""

    reason: str
    message: str


class _ContainerState(TypedDict, total=False):
    """Kubernetes container state."""

    waiting: _WaitingState
    running: dict[str, object]
    terminated: dict[str, object]


class _LastState(TypedDict, total=False):
    """Kubernetes container last state."""

    terminated: dict[str, str]


class _ContainerStatus(TypedDict, total=False):
    """Kubernetes container status."""

    state: _ContainerState
    lastState: _LastState
    ready: bool
    restartCount: int


class _PodCondition(TypedDict, total=False):
    """Kubernetes pod condition."""

    type: str
    status: str
    reason: str


class _PodMetadata(TypedDict, total=False):
    """Kubernetes pod metadata."""

    name: str


class _PodStatus(TypedDict, total=False):
    """Kubernetes pod status."""

    phase: str
    containerStatuses: list[_ContainerStatus]
    conditions: list[_PodCondition]


class _Pod(TypedDict, total=False):
    """Kubernetes pod resource."""

    metadata: _PodMetadata
    status: _PodStatus


@dataclass(frozen=True, slots=True)
class KubernetesResourceSnapshot:
    """Raw resources needed to evaluate Deployment rollout health."""

    deployments: tuple[JsonObject, ...]
    replica_sets: tuple[JsonObject, ...]
    pods: tuple[JsonObject, ...]


def _parse_resource_snapshot(stdout: str) -> KubernetesResourceSnapshot:
    """Parse a combined kubectl resource list without discarding identities."""
    raw = json.loads(stdout)
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        message = "kubectl response is not a Kubernetes resource list"
        raise TypeError(message)

    by_kind: dict[str, list[JsonObject]] = {
        "Deployment": [],
        "ReplicaSet": [],
        "Pod": [],
    }
    for item in raw["items"]:
        if isinstance(item, dict) and (kind := item.get("kind")) in by_kind:
            by_kind[cast("str", kind)].append(cast("JsonObject", item))

    return KubernetesResourceSnapshot(
        deployments=tuple(by_kind["Deployment"]),
        replica_sets=tuple(by_kind["ReplicaSet"]),
        pods=tuple(by_kind["Pod"]),
    )


def _parse_pod_list(stdout: str) -> list[_Pod]:
    """Parse kubectl JSON output to a typed pod list, returning empty on error."""
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, dict):
        return []
    items = raw.get("items", [])
    if not isinstance(items, list):
        return []
    return cast("list[_Pod]", [item for item in items if isinstance(item, dict)])


def _run_kubectl(
    args: list[str],
    *,
    namespace: str,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """Execute a kubectl command and return ``(exit_code, stdout, stderr)``."""
    cmd = ["kubectl", "-n", namespace, *args]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 1, "", f"kubectl timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", "kubectl not found in PATH"
    else:
        return result.returncode, result.stdout, result.stderr


def _restart_request(url: str, timeout: int) -> tuple[int, str, str]:
    """Issue the single permitted Kafka Connect mutation."""
    try:
        result = subprocess.run(
            ["curl", "-fsS", "-X", "POST", url],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


K8S_NAME_MAP: Final[dict[str, str]] = {
    "postgres": "nohiki-infra-postgres",
    "redis": "nohiki-infra-redis",
    "kafka": "nohiki-cp-kafka",
    "traefik": "nohiki-infra-traefik",
    **{
        name: f"nohiki-{name}"
        for name in [
            "user-auth-service",
            "user-pref-service",
            "user-upload-service",
            "user-entitlement-service",
            "bff-service",
            "doc-template-service",
            "doc-content-service",
            "doc-process-service",
            "job-query-composition-service",
            "job-ingest-schedule-service",
            "job-ingest-discovery-service",
            "job-ingest-enrichment-service",
            "job-storage-service",
            "job-correlation-evaluation-service",
            "notification-service",
            "ml-gateway-service",
            "ml-compute-service",
            "skill-graph-service",
            "frontend",
        ]
    },
}

K8S_HOST_INFRA: Final[frozenset[str]] = frozenset(
    {
        "postgres",
        "redis",
        "kafka",
        "traefik",
    }
)


def _get_waiting_reason(cs: _ContainerStatus) -> str | None:
    """Extract the waiting reason from a container status dict."""
    state = cs.get("state")
    if state is None:
        return None
    waiting = state.get("waiting")
    if waiting is None:
        return None
    return waiting.get("reason")


_CRASH_REASONS: Final[frozenset[str]] = frozenset(
    {
        "CrashLoopBackOff",
        "Error",
        "ErrImageNeverPull",
        "ImagePullBackOff",
    }
)


def _has_crash_state(container_statuses: list[_ContainerStatus]) -> bool:
    """Return True if any container is in a crash or image-pull error state."""
    return any(_get_waiting_reason(cs) in _CRASH_REASONS for cs in container_statuses)


def _parse_k8s_phase(
    phase: str,
    container_statuses: list[_ContainerStatus],
    *,
    ready: bool,
) -> ServiceStatus:
    """Map a k8s pod phase and readiness to ``ServiceStatus``."""
    match (phase, ready):
        case ("Running", True):
            return ServiceStatus.HEALTHY
        case ("Running", False):
            return ServiceStatus.CRASHED if _has_crash_state(container_statuses) else ServiceStatus.STARTING
        case ("Pending", _):
            return ServiceStatus.STARTING
        case ("Failed" | "Unknown", _):
            return ServiceStatus.CRASHED
        case ("Succeeded", _):
            return ServiceStatus.STOPPED
        case _:
            return ServiceStatus.UNHEALTHY


class KubernetesPlatform:
    """Kubernetes platform implementation using kubectl.

    Args:
        namespace: Kubernetes namespace to target (default: ``K8S_NAMESPACE`` env or ``"nohiki"``).
        local_mode: If True, infrastructure runs on host via Compose (local k3s mode).
    """

    def __init__(self, namespace: str | None = None, *, local_mode: bool | None = None) -> None:
        """Initialise the Kubernetes platform with explicit, testable routing mode."""
        self._namespace = namespace or os.getenv("K8S_NAMESPACE", "nohiki")
        self._local_mode = os.getenv("K8S_LOCAL_MODE", "true").lower() == "true" if local_mode is None else local_mode

    @property
    def target(self) -> PlatformTarget:
        """Identify this as a Kubernetes deployment target."""
        return PlatformTarget.KUBERNETES

    @property
    def api_base_url(self) -> str:
        """Base URL for the BFF API gateway."""
        default = "http://localhost:8000" if self._local_mode else "http://bff-service:8000"
        return os.getenv("E2E_BASE_URL", default)

    @property
    def kafka_bootstrap_server(self) -> str:
        """Kafka bootstrap server address for CLI tools."""
        if self._local_mode:
            return "localhost:29092"
        return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "nohiki-kafka-bootstrap:9092")

    @property
    def namespace(self) -> str:
        """Kubernetes namespace this platform operates in."""
        return self._namespace

    def is_infra_managed(self) -> bool:
        """Return True only in production k8s; False in local k3s (infra on host)."""
        return not self._local_mode

    def _uses_cluster_database(self) -> bool:
        """Return whether DATABASE_URL resolves through non-host Kubernetes DNS."""
        hostname = urlsplit(os.getenv("DATABASE_URL", "")).hostname
        return not self._local_mode and hostname not in {None, "localhost", "127.0.0.1"}

    def _kubectl(self, args: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
        """Delegate to module-level ``_run_kubectl`` with this platform's namespace."""
        return _run_kubectl(args, namespace=self._namespace, timeout=timeout)

    def get_deployment_rollout_resources(self) -> KubernetesResourceSnapshot:
        """Fetch Deployments, ReplicaSets, and pods in one kubectl invocation."""
        code, stdout, stderr = self._kubectl(
            ["get", "deployments,replicasets,pods", "-o", "json"],
            timeout=30,
        )
        if code != 0:
            message = stderr.strip() or f"kubectl exited with status {code}"
            raise RuntimeError(message)
        return _parse_resource_snapshot(stdout)

    def get_resources(
        self,
        resource: str,
        *,
        all_namespaces: bool = False,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """Return a Kubernetes resource list as kubectl JSON without mutating it."""
        args = ["get", resource, "-o", "json"]
        if all_namespaces:
            args.insert(2, "--all-namespaces")
        return self._kubectl(args, timeout=timeout)

    def _get_pod_name(self, canonical_name: str) -> str | None:
        """Return the name of the first running pod for a canonical service name.

        Args:
            canonical_name: Canonical service name.

        Returns:
            Pod name or ``None`` if no running pod found.
        """
        code, stdout, _ = self._kubectl(
            [
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/name={canonical_name}",
                "--field-selector=status.phase=Running",
                "-o",
                "jsonpath={.items[0].metadata.name}",
            ]
        )
        if code == 0 and stdout.strip():
            return stdout.strip()

        k8s_name = K8S_NAME_MAP.get(canonical_name, canonical_name)
        code, stdout, _ = self._kubectl(
            [
                "get",
                "pods",
                "--no-headers",
                "-o",
                "custom-columns=NAME:.metadata.name,STATUS:.status.phase",
            ]
        )
        if code != 0:
            return None

        for line in stdout.strip().split("\n"):
            if (parts := line.split()) and k8s_name in parts[0]:
                return parts[0]

        return None

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        """Return current status for all Nohiki pods in the namespace."""
        code, stdout, _ = self._kubectl(["get", "pods", "-o", "json"])
        if code != 0:
            return {}

        pods_data = _parse_pod_list(stdout)
        if not pods_data:
            return {}

        reverse_map = {v: k for k, v in K8S_NAME_MAP.items()}
        result: dict[str, ServiceInfo] = {}

        for pod in pods_data:
            pod_meta = pod.get("metadata") or {}
            pod_name: str = pod_meta.get("name", "")
            pod_status = pod.get("status") or {}
            phase: str = pod_status.get("phase", "Unknown")

            canonical: str | None = next(
                (canon for k8s_prefix, canon in reverse_map.items() if pod_name.startswith(k8s_prefix)),
                None,
            )
            if canonical is None:
                continue

            container_statuses: list[_ContainerStatus] = pod_status.get("containerStatuses") or []
            ready = all(cs.get("ready", False) for cs in container_statuses)
            restarts = sum(int(cs.get("restartCount", 0)) for cs in container_statuses)
            status = _parse_k8s_phase(phase, container_statuses, ready=ready)

            result[canonical] = ServiceInfo(
                name=canonical,
                status=status,
                ready=ready,
                restarts=restarts,
                details=f"phase={phase} ready={ready} restarts={restarts}",
            )

        return result

    def get_logs(self, canonical_name: str, lines: int = 50) -> str:
        """Fetch recent log lines from a pod."""
        pod_name = self._get_pod_name(canonical_name)
        if not pod_name:
            return ""
        code, stdout, stderr = self._kubectl(["logs", pod_name, f"--tail={lines}"], timeout=30)
        return stdout if code == 0 else stderr

    def exec_in_service(
        self,
        canonical_name: str,
        command: list[str],
        *,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """Use read-only direct clients in the verification Job; retain admin access elsewhere."""
        if self._uses_cluster_database():
            if canonical_name == "postgres" and command and command[0] == "pg_isready":
                code, _, stderr = psql("SELECT 1")
                return code, "accepting connections" if code == 0 else "", stderr
            if canonical_name == "redis" and command[:2] == ["redis-cli", "INFO"]:
                return valkey_info()
            return (
                2,
                "",
                f"pod exec is disabled for health verification: {canonical_name}",
            )

        pod_name = self._get_pod_name(canonical_name)
        if pod_name is None:
            return 1, "", f"No running pod found for '{canonical_name}'"
        return self._kubectl(["exec", pod_name, "--", *command], timeout=timeout)

    def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
        """Execute a psql query against the primary Nohiki database."""
        if self._uses_cluster_database():
            return psql(query, field_separator)
        if self._local_mode:
            cmd = [
                "podman",
                "exec",
                "nohiki-infra-postgres",
                "psql",
                "-U",
                "postgres",
                "-d",
                "nohiki_db",
                "-t",
                "-A",
            ]
            if field_separator:
                cmd.extend(["-F", field_separator])
            cmd.extend(["-c", query])
            try:
                r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                return 1, "", str(exc)
            else:
                return r.returncode, r.stdout, r.stderr

        psql_args = ["psql", "-U", "postgres", "-d", "nohiki_db", "-t", "-A"]
        if field_separator:
            psql_args.extend(["-F", field_separator])
        psql_args.extend(["-c", query])
        return self.exec_in_service("postgres", psql_args)

    def exec_kafka_cmd(self, args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
        """Execute Kafka metadata operations through the configured deployment path."""
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
        if not self._local_mode and bootstrap and "localhost" not in bootstrap:
            return kafka_command(args)
        if not self._local_mode:
            return self.exec_in_service("kafka", args, timeout=timeout)
        try:
            result = subprocess.run(
                ["podman", "exec", "nohiki-cp-kafka", *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return 1, "", str(exc)
        return result.returncode, result.stdout, result.stderr

    def service_url(self, canonical_name: str, port: int) -> str:
        """Return a URL routable from the health-check process."""
        if self._local_mode:
            return f"http://localhost:{port}"
        return f"http://{canonical_name}.{self._namespace}.svc.cluster.local:{port}"

    def check_port(self, host: str, port: int, *, timeout: float = 5.0) -> bool:
        """Return True if a TCP connection to ``host:port`` succeeds."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((host, port))
        except OSError:
            return False
        else:
            return True

    def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Perform an HTTP GET directly in-cluster, retaining curl for host endpoints."""
        if urlsplit(url).hostname in {"localhost", "127.0.0.1"}:
            try:
                result = subprocess.run(
                    ["curl", "-fsS", url],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                return 1, "", str(exc)
            return result.returncode, result.stdout, result.stderr
        try:
            response = httpx.get(url, timeout=timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return 1, "", str(exc)
        return 0, response.text, ""

    def restart_kafka_connector(self, connector_name: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Restart failed instances of one canonical Kafka Connect connector."""
        from health_check.config.kafka import connector_names_for

        if connector_name not in connector_names_for(self.target):
            message = f"Non-canonical connector rejected: {connector_name}"
            raise ValueError(message)
        base = self.service_url("kafka-connect", 8083)
        name = quote(connector_name, safe="")
        return _restart_request(
            f"{base}/connectors/{name}/restart?includeTasks=true&onlyFailed=true",
            timeout,
        )

    def check_oom_killed(self) -> list[str]:
        """Return names of pods that have been OOMKilled.

        Returns:
            List of pod names with OOMKilled containers.
        """
        code, stdout, _ = self._kubectl(["get", "pods", "-o", "json"])
        if code != 0:
            return []

        pods_data = _parse_pod_list(stdout)

        return [
            (pod.get("metadata") or {}).get("name", "")
            for pod in pods_data
            if any(
                (cs.get("lastState") or {}).get("terminated", {}).get("reason") == "OOMKilled"
                for cs in (pod.get("status") or {}).get("containerStatuses") or []
            )
        ]

    def check_pending_pods(self) -> list[tuple[str, str]]:
        """Return ``(pod_name, reason)`` for pods stuck in Pending state.

        Returns:
            List of ``(pod_name, reason)`` tuples.
        """
        code, stdout, _ = self._kubectl(
            [
                "get",
                "pods",
                "--field-selector=status.phase=Pending",
                "-o",
                "json",
            ]
        )
        if code != 0:
            return []

        pods_data = _parse_pod_list(stdout)

        pending: list[tuple[str, str]] = []
        for pod in pods_data:
            name: str = (pod.get("metadata") or {}).get("name", "")
            reason = "Unknown"
            for cond in (pod.get("status") or {}).get("conditions") or []:
                if cond.get("type") == "PodScheduled" and cond.get("status") == "False":
                    reason = cond.get("reason") or "Unschedulable"
                    break
            pending.append((name, reason))
        return pending

    def get_resource_usage(self) -> dict[str, dict[str, str]]:
        """Return CPU/memory usage per pod via the metrics-server.

        Returns:
            Mapping of pod name to ``{"cpu": "...", "memory": "..."}``.
        """
        code, stdout, _ = self._kubectl(["top", "pods", "--no-headers"], timeout=10)
        if code != 0:
            return {}

        usage: dict[str, dict[str, str]] = {}
        for line in stdout.strip().split("\n"):
            if (parts := line.split()) and len(parts) >= 3:
                usage[parts[0]] = {"cpu": parts[1], "memory": parts[2]}
        return usage

"""Docker Compose platform implementation."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Final
from urllib.parse import quote

from health_check.config.kafka import connector_names_for
from health_check.config.paths import COMPOSE_DIR
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus
from health_check.platform.runtime import ContainerRuntime, detect_container_runtime


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """Execute a subprocess command and return ``(exit_code, stdout, stderr)``.

    Args:
        cmd: Command and arguments as a list.
        cwd: Working directory for the subprocess.
        timeout: Maximum seconds to wait for completion.

    Returns:
        Tuple of ``(exit_code, stdout, stderr)``.
    """
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=cwd or COMPOSE_DIR,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout
        partial: str = raw.decode() if isinstance(raw, bytes) else (raw or "")
        return 1, partial, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"
    else:
        return result.returncode, result.stdout, result.stderr


COMPOSE_NAME_MAP: Final[dict[str, str]] = {
    "postgres": "nohiki-infra-postgres",
    "redis": "nohiki-infra-valkey",
    "kafka": "nohiki-cp-kafka",
    "traefik": "nohiki-infra-traefik",
    "rustfs": "nohiki-infra-rustfs",
    "qdrant": "nohiki-infra-qdrant",
    "gotenberg": "nohiki-infra-gotenberg",
    "docling": "nohiki-infra-docling",
    "kafka-connect": "nohiki-cp-kafka-connect",
    "user-auth-service": "nohiki-svc-user-auth",
    "user-pref-service": "nohiki-svc-user-pref",
    "user-upload-service": "nohiki-svc-user-upload",
    "user-entitlement-service": "nohiki-svc-user-entitlement",
    "bff-service": "nohiki-svc-bff",
    "doc-template-service": "nohiki-svc-doc-template",
    "doc-content-service": "nohiki-svc-doc-content",
    "doc-process-service": "nohiki-svc-doc-process",
    "job-query-composition-service": "nohiki-svc-job-query-composition",
    "job-ingest-schedule-service": "nohiki-svc-job-ingest-schedule",
    "job-ingest-discovery-service": "nohiki-svc-job-ingest-discovery",
    "job-ingest-enrichment-service": "nohiki-svc-job-ingest-enrichment",
    "job-storage-service": "nohiki-svc-job-storage",
    "job-correlation-evaluation-service": "nohiki-svc-job-correlation",
    "notification-service": "nohiki-svc-notification",
    "ml-gateway-service": "nohiki-svc-ml-gateway",
    "ml-compute-service": "nohiki-svc-ml-compute",
    "skill-graph-service": "nohiki-svc-skill-graph",
    "frontend": "nohiki-svc-frontend",
}


def _json_record(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _compose_ps_records(output: str) -> list[dict[str, object]]:
    if not output.strip():
        return []
    try:
        payload: object = json.loads(output)
    except json.JSONDecodeError:
        records: list[dict[str, object]] = []
        for line in output.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record := _json_record(payload):
                records.append(record)
        return records
    if isinstance(payload, list):
        return [record for item in payload if (record := _json_record(item)) is not None]
    if record := _json_record(payload):
        return [record]
    return []


def _record_string(record: dict[str, object], *keys: str) -> str:
    for key in keys:
        if isinstance(value := record.get(key), str):
            return value
    return ""


def _record_label(record: dict[str, object], *keys: str) -> str:
    labels = record.get("Labels")
    if not isinstance(labels, dict):
        return ""
    for key in keys:
        if isinstance(value := labels.get(key), str):
            return value
    return ""


def _record_service(record: dict[str, object]) -> str:
    if service := _record_string(record, "Service", "service"):
        return service
    return _record_label(record, "com.docker.compose.service", "io.podman.compose.service")


def _record_is_oneoff(record: dict[str, object]) -> bool:
    label_name = "com.docker.compose.oneoff"
    labels = record.get("Labels")
    if isinstance(labels, dict):
        value = labels.get(label_name)
        return value is True or (isinstance(value, str) and value.casefold() == "true")
    if isinstance(labels, str):
        for label in labels.split(","):
            key, separator, value = label.partition("=")
            if separator and key.strip() == label_name:
                return value.strip().casefold() == "true"
    return False


def _record_name(record: dict[str, object]) -> str:
    if name := _record_string(record, "Name", "name"):
        return name
    names = record.get("Names")
    if isinstance(names, list):
        for item in names:
            if isinstance(item, str):
                return item
    return ""


def _podman_record_is_primary(record: dict[str, object], name: str) -> bool:
    project = _record_label(record, "com.docker.compose.project", "io.podman.compose.project")
    service = _record_service(record)
    if not project or not service:
        return False
    return re.fullmatch(rf"{re.escape(project)}_{re.escape(service)}_[1-9]\d*", name) is not None


def _parse_compose_status(status_str: str) -> ServiceStatus:
    """Parse a Docker/Podman Compose container status string into ``ServiceStatus``.

    Args:
        status_str: Raw status string from ``ps --format '{{.Status}}'``.

    Returns:
        The corresponding ``ServiceStatus`` value.
    """
    s = status_str.lower()
    if "unhealthy" in s or "exited" in s:
        return ServiceStatus.CRASHED
    if "healthy" in s:
        return ServiceStatus.HEALTHY
    if "starting" in s:
        return ServiceStatus.STARTING
    return ServiceStatus.UNHEALTHY


def _parse_duration_hours(duration: str) -> float:
    if match := re.search(r"(\d+)\s*(second|minute|hour|day|week)", duration.casefold()):
        value = int(match.group(1))
        multipliers = {
            "second": 1 / 3600,
            "minute": 1 / 60,
            "hour": 1.0,
            "day": 24.0,
            "week": 168.0,
        }
        return value * multipliers[match.group(2)]
    return 0.0


def _started_at_uptime_hours(started_at: object) -> float:
    if isinstance(started_at, bool):
        return 0.0
    if isinstance(started_at, int | float):
        return max(time.time() - float(started_at), 0.0) / 3600.0
    return 0.0


def _parse_compose_uptime_hours(status_str: str) -> float:
    """Extract uptime in hours from a Compose status string.

    Args:
        status_str: Raw status string, e.g. ``"Up 2 hours (healthy)"``.

    Returns:
        Uptime in hours, or ``0.0`` if not parseable.
    """
    s = status_str.lower()
    if "up" not in s:
        return 0.0

    return _parse_duration_hours(s)


class ComposePlatform:
    """Docker Compose platform implementation.

    Uses the injected ``ContainerRuntime`` for all container operations, enabling
    transparent support for both Docker and Podman without subclassing.

    Args:
        runtime: Container runtime to use. Auto-detected if not provided.
        compose_dir: Directory containing ``docker-compose.yml``.
        compose_file: Compose file name within ``compose_dir``.
    """

    def __init__(
        self,
        runtime: ContainerRuntime | None = None,
        compose_dir: Path | None = None,
        *,
        compose_file: str = "docker-compose.yml",
    ) -> None:
        """Initialise the Compose platform with an optional runtime override."""
        self._runtime: ContainerRuntime = runtime or detect_container_runtime()
        self._compose_dir: Path = compose_dir or COMPOSE_DIR
        self._compose_file: Path = self._compose_dir / compose_file
        self._container_names: dict[str, str] = {}

    @property
    def target(self) -> PlatformTarget:
        """Identify this as a Compose deployment target."""
        return PlatformTarget.COMPOSE

    @property
    def api_base_url(self) -> str:
        """Base URL for the BFF API gateway."""
        return os.getenv("E2E_BASE_URL", "http://localhost:8000")

    @property
    def kafka_bootstrap_server(self) -> str:
        """Kafka bootstrap server address for CLI tools."""
        return "localhost:29092"

    @property
    def runtime(self) -> ContainerRuntime:
        """The container runtime in use."""
        return self._runtime

    def is_infra_managed(self) -> bool:
        """Return True -- Compose manages all infrastructure services."""
        return True

    def _container_name(self, canonical: str) -> str:
        """Translate a canonical service name to its Compose service name.

        Args:
            canonical: Canonical service name, e.g. ``"postgres"``.

        Returns:
            Compose service name resolved by the active Compose provider.
        """
        return COMPOSE_NAME_MAP.get(canonical, canonical)

    def _compose_command(self, *args: str) -> list[str]:
        return [self._runtime.value, "compose", "-f", str(self._compose_file), *args]

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        """Return current status for all Nohiki Compose services.

        Returns:
            Mapping of canonical service name to ``ServiceInfo``.
        """
        command = self._compose_command("ps", "--all", "--format", "json")
        code, stdout, _ = _run_cmd(command, cwd=self._compose_dir)
        if code != 0 and self._runtime is ContainerRuntime.PODMAN:
            command = self._compose_command("ps", "--format", "json")
            code, stdout, _ = _run_cmd(command, cwd=self._compose_dir)
        if code != 0:
            self._container_names = {}
            return {}

        canonical_by_service = {service: canonical for canonical, service in COMPOSE_NAME_MAP.items()}
        result: dict[str, ServiceInfo] = {}
        container_names: dict[str, str] = {}
        for record in _compose_ps_records(stdout):
            service = _record_service(record)
            name = _record_name(record)
            podman_run = self._runtime is ContainerRuntime.PODMAN and not _podman_record_is_primary(record, name)
            if _record_is_oneoff(record) or podman_run:
                continue
            canonical = canonical_by_service.get(service)
            if canonical is None:
                canonical = canonical_by_service.get(name)
            if canonical is None:
                if not service.startswith("nohiki"):
                    continue
                canonical = service

            if name:
                container_names[canonical] = name
            state = _record_string(record, "State", "state")
            status_str = _record_string(record, "Status", "status", "State", "state")
            health = _record_string(record, "Health", "health")
            if health and health.casefold() not in status_str.casefold():
                status_str = f"{status_str} ({health})"
            status = _parse_compose_status(status_str)
            uptime_hours = _parse_compose_uptime_hours(status_str)
            if uptime_hours == 0.0 and (running_for := _record_string(record, "RunningFor", "running_for")):
                uptime_hours = _parse_duration_hours(running_for)
            if uptime_hours == 0.0 and state.casefold() == "running":
                uptime_hours = _started_at_uptime_hours(record.get("StartedAt"))

            result[canonical] = ServiceInfo(
                name=canonical,
                status=status,
                ready=status == ServiceStatus.HEALTHY,
                uptime_seconds=uptime_hours * 3600.0,
                details=status_str,
            )

        self._container_names = container_names
        return result

    def get_logs(self, canonical_name: str, lines: int = 50) -> str:
        """Fetch recent log lines from a container.

        Args:
            canonical_name: Canonical service name.
            lines: Number of tail lines to retrieve.

        Returns:
            Log output as a string, or empty string on failure.
        """
        container = self._container_names.get(canonical_name)
        if container is None:
            return ""
        code, stdout, _ = _run_cmd(
            [self._runtime.value, "logs", "--tail", str(lines), container],
            cwd=self._compose_dir,
            timeout=30,
        )
        return stdout if code == 0 else ""

    def exec_in_service(
        self,
        canonical_name: str,
        command: list[str],
        *,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """Execute a command inside a running container.

        Args:
            canonical_name: Canonical service name.
            command: Command and arguments to execute.
            timeout: Maximum seconds to wait.

        Returns:
            Tuple of ``(exit_code, stdout, stderr)``.
        """
        container = self._container_names.get(canonical_name)
        if container is None:
            return 1, "", f"Container not discovered for service: {canonical_name}"
        return _run_cmd(
            [self._runtime.value, "exec", container, *command],
            cwd=self._compose_dir,
            timeout=timeout,
        )

    def exec_psql(
        self,
        query: str,
        *,
        field_separator: str = "",
    ) -> tuple[int, str, str]:
        """Execute a psql query against the primary Nohiki database.

        Args:
            query: SQL query string.
            field_separator: Optional column separator for output.

        Returns:
            Tuple of ``(exit_code, stdout, stderr)``.
        """
        cmd = [
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
        return self.exec_in_service("postgres", cmd, timeout=10)

    def exec_kafka_cmd(self, args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
        """Execute a Kafka CLI command inside the Kafka container.

        Args:
            args: Kafka CLI command and arguments (e.g. ``["kafka-topics", "--list", ...]``).
            timeout: Maximum seconds to wait.

        Returns:
            Tuple of ``(exit_code, stdout, stderr)``.
        """
        return self.exec_in_service("kafka", args, timeout=timeout)

    def service_url(self, canonical_name: str, port: int) -> str:
        """Return the host-published URL for a Compose service."""
        del canonical_name
        return f"http://localhost:{port}"

    def check_port(self, host: str, port: int, *, timeout: float = 5.0) -> bool:
        """Return True if a TCP connection to ``host:port`` succeeds.

        Args:
            host: Target hostname or IP address.
            port: Target TCP port.
            timeout: Connection timeout in seconds.

        Returns:
            True if connection succeeded, False otherwise.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((host, port))
        except OSError:
            return False
        else:
            return True

    def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Perform an HTTP GET request via curl.

        Args:
            url: Full URL to request.
            timeout: Maximum seconds to wait.

        Returns:
            Tuple of ``(exit_code, response_body, stderr)``.
        """
        return _run_cmd(["curl", "-fsS", url], cwd=self._compose_dir, timeout=timeout)

    def restart_kafka_connector(self, connector_name: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Restart failed instances of one canonical Kafka Connect connector."""
        if connector_name not in connector_names_for(self.target):
            message = f"Non-canonical connector rejected: {connector_name}"
            raise ValueError(message)
        base = self.service_url("kafka-connect", 8083)
        name = quote(connector_name, safe="")
        return _run_cmd(
            ["curl", "-fsS", "-X", "POST", f"{base}/connectors/{name}/restart?includeTasks=true&onlyFailed=true"],
            cwd=self._compose_dir,
            timeout=timeout,
        )

    def check_pending_pods(self) -> list[tuple[str, str]]:
        """Return no pending pods because Compose does not use Kubernetes."""
        return []

    def get_resource_usage(self) -> dict[str, dict[str, str]]:
        """Return no Kubernetes resource usage for Compose deployments."""
        return {}

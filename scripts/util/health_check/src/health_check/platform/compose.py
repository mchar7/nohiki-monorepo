"""Docker Compose platform implementation."""

from __future__ import annotations

import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Final
from urllib.parse import quote

from health_check.config.kafka import OUTBOX_CONNECTOR_NAMES
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

    if match := re.search(r"up\s+(\d+)\s*(second|minute|hour|day|week)", s):
        value = int(match.group(1))
        multipliers = {
            "second": 1 / 3600,
            "minute": 1 / 60,
            "hour": 1.0,
            "day": 24.0,
            "week": 168.0,
        }
        return value * multipliers.get(match.group(2), 0.0)

    return 0.0


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
        """Translate a canonical service name to its Compose container name.

        Args:
            canonical: Canonical service name, e.g. ``"postgres"``.

        Returns:
            The canonical container name when no Compose project is configured,
            otherwise Compose's ``<project>_<service>_1`` container name.
        """
        service = COMPOSE_NAME_MAP.get(canonical, canonical)
        if project := os.getenv("COMPOSE_PROJECT_NAME"):
            return f"{project}_{service}_1"
        return service

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        """Return current status for all running Nohiki containers.

        Returns:
            Mapping of canonical service name to ``ServiceInfo``.
        """
        code, stdout, _ = _run_cmd(
            [self._runtime.value, "ps", "--format", "{{.Names}} {{.Status}}"],
            cwd=self._compose_dir,
        )
        if code != 0:
            return {}

        reverse_map = {self._container_name(canonical): canonical for canonical in COMPOSE_NAME_MAP}
        result: dict[str, ServiceInfo] = {}

        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue

            compose_name, status_str = parts
            canonical = reverse_map.get(compose_name)
            if canonical is None:
                if not compose_name.startswith("nohiki"):
                    continue
                canonical = compose_name
            status = _parse_compose_status(status_str)
            uptime_hours = _parse_compose_uptime_hours(status_str)

            result[canonical] = ServiceInfo(
                name=canonical,
                status=status,
                ready=status == ServiceStatus.HEALTHY,
                uptime_seconds=uptime_hours * 3600.0,
                details=status_str,
            )

        return result

    def get_logs(self, canonical_name: str, lines: int = 50) -> str:
        """Fetch recent log lines from a container.

        Args:
            canonical_name: Canonical service name.
            lines: Number of tail lines to retrieve.

        Returns:
            Log output as a string, or empty string on failure.
        """
        container = self._container_name(canonical_name)
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
        container = self._container_name(canonical_name)
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
            self._runtime.value,
            "exec",
            self._container_name("postgres"),
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
        return _run_cmd(cmd, cwd=self._compose_dir, timeout=10)

    def exec_kafka_cmd(self, args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
        """Execute a Kafka CLI command inside the Kafka container.

        Args:
            args: Kafka CLI command and arguments (e.g. ``["kafka-topics", "--list", ...]``).
            timeout: Maximum seconds to wait.

        Returns:
            Tuple of ``(exit_code, stdout, stderr)``.
        """
        return _run_cmd(
            [self._runtime.value, "exec", self._container_name("kafka"), *args],
            cwd=self._compose_dir,
            timeout=timeout,
        )

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
        if connector_name not in OUTBOX_CONNECTOR_NAMES:
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

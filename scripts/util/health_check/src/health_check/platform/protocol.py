"""Platform protocol defining the unified interface for all deployment targets."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from health_check.platform.models import PlatformTarget, ServiceInfo


@runtime_checkable
class Platform(Protocol):
    """Protocol for platform-specific container/pod operations.

    Implementations provide a unified interface so health checks work
    identically whether running against Docker Compose or Kubernetes.
    """

    @property
    def target(self) -> PlatformTarget:
        """Identify which deployment target this platform represents."""
        ...

    @property
    def api_base_url(self) -> str:
        """Base URL for the BFF API gateway."""
        ...

    @property
    def kafka_bootstrap_server(self) -> str:
        """Kafka bootstrap server address for CLI tools."""
        ...

    def service_url(self, canonical_name: str, port: int) -> str:
        """Return a platform-routable HTTP base URL for a service."""
        ...

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        """Return current status for all known services, keyed by canonical name."""
        ...

    def get_logs(self, canonical_name: str, lines: int = 50) -> str:
        """Fetch recent log lines for a service by canonical name."""
        ...

    def exec_in_service(
        self,
        canonical_name: str,
        command: list[str],
        *,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """Execute a command inside a running service container/pod.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        ...

    def exec_psql(
        self,
        query: str,
        *,
        field_separator: str = "",
    ) -> tuple[int, str, str]:
        """Execute a psql query against the primary Nohiki database.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        ...

    def exec_kafka_cmd(
        self,
        args: list[str],
        *,
        timeout: int = 15,
    ) -> tuple[int, str, str]:
        """Execute a Kafka CLI command (kafka-topics, kafka-consumer-groups, etc.).

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        ...

    def check_port(self, host: str, port: int, *, timeout: float = 5.0) -> bool:
        """Return True if a TCP connection to host:port succeeds within timeout."""
        ...

    def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Perform an HTTP GET request via curl.

        Returns:
            Tuple of (exit_code, response_body, stderr).
        """
        ...

    def restart_kafka_connector(self, connector_name: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Restart failed connector/tasks for one canonical connector only."""
        ...

    def is_infra_managed(self) -> bool:
        """Return True if this platform manages infrastructure (postgres, redis, kafka).

        Docker Compose returns True. Kubernetes local mode returns False
        (infra runs on host). Kubernetes production returns True.
        """
        ...

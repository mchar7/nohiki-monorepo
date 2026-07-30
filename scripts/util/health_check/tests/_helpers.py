"""Shared helpers for the health_check test suite."""

from __future__ import annotations

from dataclasses import dataclass

from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
)
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus


@dataclass
class MockPlatform:
    """Configurable mock implementation of the Platform protocol."""

    target: PlatformTarget = PlatformTarget.COMPOSE
    api_base_url: str = "http://localhost:8000"
    kafka_bootstrap_server: str = "localhost:29092"

    _service_statuses: dict[str, ServiceInfo] | None = None
    _logs: dict[str, str] | None = None
    _psql_result: tuple[int, str, str] = (0, "", "")
    _kafka_cmd_result: tuple[int, str, str] = (0, "", "")
    _curl_result: tuple[int, str, str] = (0, "", "")
    _exec_in_service_result: tuple[int, str, str] = (0, "", "")
    _restart_kafka_connector_result: tuple[int, str, str] = (0, "", "")
    restart_kafka_connector_calls: list[tuple[str, int]] | None = None
    _port_open: bool = True
    _is_infra_managed: bool = True

    def service_url(self, canonical_name: str, port: int) -> str:
        """Return a deterministic fake service URL."""
        return f"http://{canonical_name}:{port}"

    def get_service_statuses(self) -> dict[str, ServiceInfo]:
        """Return mock service statuses."""
        return self._service_statuses or {}

    def get_logs(self, canonical_name: str, lines: int = 50) -> str:
        """Return mock log output."""
        logs = self._logs or {}
        return logs.get(canonical_name, "")

    def exec_psql(self, query: str, *, field_separator: str = "") -> tuple[int, str, str]:
        """Return mock psql result."""
        return self._psql_result

    def exec_kafka_cmd(self, args: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
        """Return mock kafka command result."""
        return self._kafka_cmd_result

    def curl(self, url: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Return mock curl result."""
        return self._curl_result

    def restart_kafka_connector(self, connector_name: str, *, timeout: int = 10) -> tuple[int, str, str]:
        """Record a typed connector restart without conflating it with GET curl."""
        if self.restart_kafka_connector_calls is None:
            self.restart_kafka_connector_calls = []
        self.restart_kafka_connector_calls.append((connector_name, timeout))
        return self._restart_kafka_connector_result

    def exec_in_service(
        self,
        canonical_name: str,
        command: list[str],
        *,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """Return mock exec-in-service result."""
        return self._exec_in_service_result

    def check_port(self, host: str, port: int, *, timeout: float = 5.0) -> bool:
        """Return mock port probe result."""
        return self._port_open

    def is_infra_managed(self) -> bool:
        """Return whether infrastructure is managed."""
        return self._is_infra_managed


def make_service_info(
    *,
    name: str = "test-service",
    status: ServiceStatus = ServiceStatus.HEALTHY,
    ready: bool = True,
    restarts: int = 0,
    uptime_seconds: float = 3600.0,
) -> ServiceInfo:
    """Build a ServiceInfo with sensible defaults."""
    return ServiceInfo(
        name=name,
        status=status,
        ready=ready,
        restarts=restarts,
        uptime_seconds=uptime_seconds,
    )


def make_check_result(
    *,
    check_id: str = "test_check",
    name: str = "Test Check",
    category: CheckCategory = CheckCategory.INFRASTRUCTURE,
    status: CheckStatus = CheckStatus.PASSED,
    summary: str = "OK",
    details: tuple[str, ...] = (),
    platform: PlatformTarget = PlatformTarget.COMPOSE,
) -> CheckResult:
    """Build a CheckResult with sensible defaults."""
    return CheckResult(
        check_id=check_id,
        name=name,
        category=category,
        status=status,
        summary=summary,
        details=details,
        platform=platform,
    )


def make_metadata(
    *,
    check_id: str = "test_check",
    name: str = "Test Check",
    category: CheckCategory = CheckCategory.INFRASTRUCTURE,
    platforms: frozenset[PlatformTarget] | None = None,
    depends_on: frozenset[str] = frozenset(),
    timeout_seconds: float = 30.0,
) -> CheckMetadata:
    """Build a CheckMetadata with sensible defaults."""
    return CheckMetadata(
        check_id=check_id,
        name=name,
        category=category,
        platforms=platforms or frozenset({PlatformTarget.COMPOSE}),
        depends_on=depends_on,
        timeout_seconds=timeout_seconds,
    )

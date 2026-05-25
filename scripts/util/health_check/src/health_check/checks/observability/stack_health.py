"""Health check: Prometheus, Grafana, Tempo, Mimir, Loki, Pyroscope, and Phoenix are healthy."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from health_check.config.services import (
    GRAFANA_EXPECTED_DASHBOARD_UIDS,
    GRAFANA_EXPECTED_DATASOURCES,
    OBSERVABILITY_CONTAINER_NAMES,
)
from health_check.config.thresholds import (
    GRAFANA_ADMIN_PASSWORD,
    GRAFANA_ADMIN_USER,
    GRAFANA_DEFAULT_URL,
    HTTP_CHECK_TIMEOUT_SECONDS,
    LOKI_DEFAULT_URL,
    MIMIR_DEFAULT_URL,
    PHOENIX_DEFAULT_URL,
    PROMETHEUS_DEFAULT_URL,
    PYROSCOPE_DEFAULT_URL,
    TEMPO_DEFAULT_URL,
)
from health_check.core.base import HealthCheck
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
)
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="observability_stack",
    name="Observability Stack",
    category=CheckCategory.OBSERVABILITY,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=60.0,
    description="Verify metrics, logs, traces, Grafana dashboards, and datasources; Phoenix is disabled on k3s.",
)

_TIMEOUT: Final[int] = int(HTTP_CHECK_TIMEOUT_SECONDS)

_GRAFANA_AUTH_PREFIX: Final[str] = (
    f"http://{GRAFANA_ADMIN_USER}:{GRAFANA_ADMIN_PASSWORD}@" + GRAFANA_DEFAULT_URL.removeprefix("http://")
)


@dataclass(frozen=True, slots=True)
class _ObsEndpoint:
    """URL and human-readable description for a single observability service health probe."""

    url: str
    description: str


_COMPOSE_HEALTH_ENDPOINTS: Final[tuple[_ObsEndpoint, ...]] = (
    _ObsEndpoint(f"{PROMETHEUS_DEFAULT_URL}/-/healthy", "Prometheus"),
    _ObsEndpoint(f"{GRAFANA_DEFAULT_URL}/api/health", "Grafana"),
    _ObsEndpoint(f"{TEMPO_DEFAULT_URL}/ready", "Tempo"),
    _ObsEndpoint(f"{MIMIR_DEFAULT_URL}/ready", "Mimir"),
    _ObsEndpoint(f"{LOKI_DEFAULT_URL}/ready", "Loki"),
    _ObsEndpoint(f"{PYROSCOPE_DEFAULT_URL}/ready", "Pyroscope"),
    _ObsEndpoint(f"{PHOENIX_DEFAULT_URL}/healthz", "Phoenix"),
)


def _health_endpoints(target: PlatformTarget) -> tuple[_ObsEndpoint, ...]:
    """Resolve health endpoints for the selected deployment target."""
    if target is PlatformTarget.COMPOSE:
        return _COMPOSE_HEALTH_ENDPOINTS
    return (
        _ObsEndpoint(
            os.getenv("PROMETHEUS_URL", "http://prometheus-operated:9090") + "/-/healthy",
            "Prometheus",
        ),
        _ObsEndpoint(
            os.getenv("GRAFANA_URL", "http://grafana-service:3000") + "/api/health",
            "Grafana",
        ),
        _ObsEndpoint(os.getenv("TEMPO_URL", "http://tempo:3200") + "/ready", "Tempo"),
        _ObsEndpoint(os.getenv("MIMIR_URL", "http://mimir-nginx:8080") + "/ready", "Mimir"),
        _ObsEndpoint(os.getenv("LOKI_URL", "http://loki-gateway:80") + "/ready", "Loki"),
        _ObsEndpoint(os.getenv("PYROSCOPE_URL", "http://pyroscope:4040") + "/ready", "Pyroscope"),
    )


def _observability_container_failures(
    statuses: dict[str, ServiceInfo],
) -> tuple[str, ...]:
    """Return exact missing or unhealthy configured observability components."""
    return tuple(
        f"{name}: {info.status.value if info is not None else 'missing'}"
        for name in OBSERVABILITY_CONTAINER_NAMES
        if (info := statuses.get(name)) is None or info.status != ServiceStatus.HEALTHY
    )


async def _check_endpoint(platform: Platform, endpoint: _ObsEndpoint) -> str | None:
    """Return a failure message if the health endpoint is unreachable.

    Args:
        platform: Active platform for HTTP curl.
        endpoint: Service description and health URL.

    Returns:
        Failure description string if unreachable, else ``None``.
    """
    code, _, _ = await asyncio.to_thread(platform.curl, endpoint.url, timeout=_TIMEOUT)
    return f"{endpoint.description}: unreachable at {endpoint.url}" if code != 0 else None


def _grafana_auth_prefix(target: PlatformTarget) -> str:
    """Return a platform-appropriate Grafana URL with credentials."""
    if target is PlatformTarget.COMPOSE:
        return _GRAFANA_AUTH_PREFIX
    base = os.getenv("GRAFANA_URL", "http://grafana-service:3000")
    return f"http://{GRAFANA_ADMIN_USER}:{GRAFANA_ADMIN_PASSWORD}@{base.removeprefix('http://')}"


async def _check_grafana_datasources(platform: Platform) -> list[str]:
    """Verify expected Grafana datasources are provisioned.

    Args:
        platform: Active platform for HTTP curl.

    Returns:
        List of failure description strings (empty if all datasources present).
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{_grafana_auth_prefix(platform.target)}/api/datasources",
        timeout=_TIMEOUT,
    )
    if code != 0:
        return ["Grafana: cannot query datasources API (check credentials or connectivity)"]
    try:
        sources = json.loads(stdout)
        found = {s.get("name") for s in sources if isinstance(s, dict)}
        return [
            f"Grafana: datasource '{name}' not provisioned"
            for name in GRAFANA_EXPECTED_DATASOURCES
            if name not in found
        ]
    except json.JSONDecodeError, ValueError, TypeError:
        return ["Grafana: cannot parse datasources response"]


async def _check_grafana_dashboards(platform: Platform) -> list[str]:
    """Verify expected Grafana dashboards are provisioned.

    Args:
        platform: Active platform for HTTP curl.

    Returns:
        List of failure description strings (empty if all dashboards present).
    """
    code, stdout, _ = await asyncio.to_thread(
        platform.curl,
        f"{_grafana_auth_prefix(platform.target)}/api/search?type=dash-db",
        timeout=_TIMEOUT,
    )
    if code != 0:
        return ["Grafana: cannot query dashboards API (check credentials or connectivity)"]
    try:
        boards = json.loads(stdout)
        found = {b.get("uid") for b in boards if isinstance(b, dict)}
        return [
            f"Grafana: dashboard '{uid}' not provisioned" for uid in GRAFANA_EXPECTED_DASHBOARD_UIDS if uid not in found
        ]
    except json.JSONDecodeError, ValueError, TypeError:
        return ["Grafana: cannot parse dashboards response"]


class ObservabilityStackCheck(HealthCheck):
    """Verify all observability containers are running with dashboards and datasources provisioned."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the full observability stack check."""
        if platform.target is PlatformTarget.COMPOSE:
            statuses = await asyncio.to_thread(platform.get_service_statuses)
            present = set(statuses).intersection(OBSERVABILITY_CONTAINER_NAMES)
            if not present:
                return self._make_result(
                    CheckStatus.SKIPPED,
                    "Observability profile not deployed",
                    remediation_hint="Start the configured observability profile",
                )
            container_failures = _observability_container_failures(statuses)
            if container_failures:
                return self._make_result(
                    CheckStatus.FAILED,
                    f"{len(container_failures)} required observability component(s) unavailable",
                    details=container_failures,
                    remediation_hint="Restore every configured observability component",
                )

        endpoints = _health_endpoints(platform.target)
        if platform.target is PlatformTarget.KUBERNETES:
            endpoints += (
                _ObsEndpoint(
                    os.getenv("PROMETHEUS_URL", "http://prometheus-operated:9090") + "/api/v1/query?query=up",
                    "representative metric",
                ),
                _ObsEndpoint(
                    os.getenv("LOKI_URL", "http://loki-gateway:80")
                    + "/loki/api/v1/query_range?query=%7Bnamespace%3D%22nohiki%22%7D&limit=1",
                    "representative log",
                ),
                _ObsEndpoint(
                    os.getenv("TEMPO_URL", "http://tempo:3200") + "/api/search?limit=1",
                    "representative trace",
                ),
                _ObsEndpoint(
                    os.getenv("OTEL_COLLECTOR_URL", "http://nohiki-collector-collector:8888") + "/metrics",
                    "collector pipeline",
                ),
            )

        async with asyncio.TaskGroup() as tg:
            endpoint_tasks = [tg.create_task(_check_endpoint(platform, ep)) for ep in endpoints]
            datasource_task = tg.create_task(_check_grafana_datasources(platform))
            dashboard_task = tg.create_task(_check_grafana_dashboards(platform))

        failures: list[str] = []
        failures.extend(msg for t in endpoint_tasks if (msg := t.result()) is not None)
        failures.extend(datasource_task.result())
        failures.extend(dashboard_task.result())

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} observability issue(s)",
                details=tuple(failures),
                remediation_hint=(
                    "Restore the Kubernetes observability stack"
                    if platform.target is PlatformTarget.KUBERNETES
                    else "Deploy with: COMPOSE_PROFILE=observability "
                    "COMPOSE_OVERRIDE_FILE=docker-compose.observability.yml "
                    "sh infra/compose/scripts/preflight.sh up -d"
                ),
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(endpoints)} enabled observability services healthy with dashboards provisioned; "
            "Phoenix disabled on k3s"
            if platform.target is PlatformTarget.KUBERNETES
            else f"All {len(endpoints)} observability services healthy with dashboards provisioned",
        )

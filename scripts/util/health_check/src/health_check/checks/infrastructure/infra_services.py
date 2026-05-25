"""Health check: all infrastructure services are healthy."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.services import INFRASTRUCTURE_SERVICES
from health_check.config.thresholds import KAFKA_PORT, POSTGRES_PORT, REDIS_PORT
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_INFRA_HOST_PORTS: Final[dict[str, int]] = {
    "postgres": POSTGRES_PORT,
    "redis": REDIS_PORT,
    "kafka": KAFKA_PORT,
}

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="infra_services",
    name="Infrastructure Services",
    category=CheckCategory.INFRASTRUCTURE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    timeout_seconds=30.0,
    description="Verify postgres, redis, kafka, and traefik are healthy.",
)


def _port_failures(port_results: dict[str, bool]) -> list[str]:
    """Convert port probe results to failure messages."""
    return [f"{svc}: port {_INFRA_HOST_PORTS[svc]} not accessible" for svc, ok in port_results.items() if not ok]


def _svc_failure(svc: str, info: ServiceInfo | None) -> str | None:
    """Return a failure message for a single service, or None if healthy."""
    if info is None:
        return f"{svc}: not found"
    return f"{svc}: {info.status.value}" if info.status != ServiceStatus.HEALTHY else None


def _status_failures(statuses: dict[str, ServiceInfo]) -> list[str]:
    """Return failure messages for unhealthy infrastructure containers."""
    return [msg for svc in INFRASTRUCTURE_SERVICES if (msg := _svc_failure(svc, statuses.get(svc))) is not None]


def _build_result(check: HealthCheck, failures: list[str]) -> CheckResult:
    """Produce a CheckResult from aggregated failure messages."""
    if failures:
        return check._make_result(
            CheckStatus.FAILED,
            f"{len(failures)} infrastructure service(s) unhealthy",
            details=tuple(failures),
            remediation_hint="Inspect logs with: just logs <service>",
        )
    return check._make_result(
        CheckStatus.PASSED,
        f"All {len(INFRASTRUCTURE_SERVICES)} infrastructure services healthy",
    )


async def _host_mode_failures(platform: Platform) -> list[str]:
    """Check infrastructure via port probes (k8s non-managed mode)."""
    async with asyncio.TaskGroup() as tg:
        tasks = {
            svc: tg.create_task(asyncio.to_thread(platform.check_port, "localhost", port))
            for svc, port in _INFRA_HOST_PORTS.items()
        }
    return _port_failures({svc: t.result() for svc, t in tasks.items()})


async def _managed_mode_failures(platform: Platform) -> list[str]:
    """Check infrastructure via container/pod status."""
    statuses = await asyncio.to_thread(platform.get_service_statuses)
    return _status_failures(statuses)


class InfraServicesCheck(HealthCheck):
    """Verify all infrastructure services (postgres, redis, kafka, traefik) are healthy."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the infrastructure services health check."""
        is_k8s_host = platform.target == PlatformTarget.KUBERNETES and not platform.is_infra_managed()
        failures = await (_host_mode_failures(platform) if is_k8s_host else _managed_mode_failures(platform))
        return _build_result(self, failures)

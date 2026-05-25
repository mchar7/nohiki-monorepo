"""Health check: PostgreSQL is accepting connections."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import POSTGRES_PORT
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="postgres_connectivity",
    name="PostgreSQL Connectivity",
    category=CheckCategory.INFRASTRUCTURE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=15.0,
    description="Verify PostgreSQL is accepting connections via pg_isready.",
)

_FAIL_MSG: Final[str] = "PostgreSQL not accepting connections"
_OK_MSG: Final[str] = "PostgreSQL accepting connections"
_HINT: Final[str] = "Run: just logs postgres -- check for startup errors or resource exhaustion"


async def _check_host_connectivity(platform: Platform) -> bool:
    """Probe the postgres port in k8s non-managed (host) mode."""
    return await asyncio.to_thread(platform.check_port, "localhost", POSTGRES_PORT)


async def _check_container_connectivity(platform: Platform) -> bool:
    """Run pg_isready inside the postgres container/pod."""
    code, _, _ = await asyncio.to_thread(
        platform.exec_in_service,
        "postgres",
        ["pg_isready", "-U", "postgres"],
        timeout=10,
    )
    return code == 0


class PostgresConnectivityCheck(HealthCheck):
    """Verify PostgreSQL is reachable and accepting connections."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the PostgreSQL connectivity check."""
        is_k8s_host = platform.target == PlatformTarget.KUBERNETES and not platform.is_infra_managed()
        ok = await (_check_host_connectivity(platform) if is_k8s_host else _check_container_connectivity(platform))
        if not ok:
            return self._make_result(CheckStatus.FAILED, _FAIL_MSG, remediation_hint=_HINT)
        return self._make_result(CheckStatus.PASSED, _OK_MSG)

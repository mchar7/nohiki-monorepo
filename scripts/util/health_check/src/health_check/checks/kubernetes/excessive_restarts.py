"""Health check: no pods have excessive restart counts."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import K8S_RESTART_THRESHOLD
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="k8s_excessive_restarts",
    name="K8s Excessive Restarts",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=20.0,
    description=f"Detect pods with more than {K8S_RESTART_THRESHOLD} restarts.",
)


class K8sExcessiveRestartsCheck(HealthCheck):
    """Detect pods with restart counts indicating instability."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the excessive restarts check."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        statuses = await asyncio.to_thread(platform.get_service_statuses)
        failures = [
            f"{name}: {info.restarts} restarts"
            for name, info in statuses.items()
            if info.restarts > K8S_RESTART_THRESHOLD
        ]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} service(s) with excessive restarts",
                details=tuple(failures),
                remediation_hint="Inspect crashing pod logs: kubectl logs <pod> --previous",
            )
        return self._make_result(CheckStatus.PASSED, "All pod restart counts within threshold")

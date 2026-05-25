"""Health check: no pods were OOMKilled."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="k8s_oom_killed",
    name="K8s OOMKilled",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=20.0,
    description="Detect pods that were OOMKilled (memory limit exceeded).",
)


class K8sOomKilledCheck(HealthCheck):
    """Detect pods recently terminated due to out-of-memory conditions."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the OOMKilled detection check."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        oom_pods = await asyncio.to_thread(platform.check_oom_killed)
        if oom_pods:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(oom_pods)} pod(s) OOMKilled",
                details=tuple(oom_pods),
                remediation_hint="Increase memory limits in Helm values.yaml for affected services",
            )
        return self._make_result(CheckStatus.PASSED, "No OOMKilled pods")

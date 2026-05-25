"""Health check: no pods are stuck in Pending state."""

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
    check_id="k8s_pending_pods",
    name="K8s Pending Pods",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=20.0,
    description="Detect pods stuck in Pending state (scheduling failures, resource pressure).",
)


class K8sPendingPodsCheck(HealthCheck):
    """Detect pods stuck in Pending state indicating scheduling or resource issues."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the pending pods check."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        pending = await asyncio.to_thread(platform.check_pending_pods)
        if pending:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(pending)} pod(s) stuck in Pending",
                details=tuple(f"{name}: {reason}" for name, reason in pending),
                remediation_hint="Inspect pod events: kubectl describe pod <name>",
            )
        return self._make_result(CheckStatus.PASSED, "No pending pods")

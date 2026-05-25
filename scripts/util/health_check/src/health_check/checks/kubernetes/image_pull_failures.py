"""Health check for Kubernetes container image pull failures."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks.kubernetes._resources import (
    JsonObject,
    object_field,
    object_list,
    read_resources,
    resource_name,
    string_field,
)
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_IMAGE_PULL_FAILURES: Final[frozenset[str]] = frozenset({"ErrImagePull", "ImagePullBackOff", "ErrImageNeverPull"})
_STATUS_FIELDS: Final[tuple[str, ...]] = (
    "initContainerStatuses",
    "containerStatuses",
    "ephemeralContainerStatuses",
)
_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="k8s_image_pull_failures",
    name="K8s Image Pull Failures",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    timeout_seconds=20.0,
    description="Detect containers blocked by Kubernetes image pull failures.",
)


def _pull_failures(pod: JsonObject) -> tuple[str, ...]:
    """Return redacted container pull failures for one pod."""
    pod_name = resource_name(pod)
    status = object_field(pod, "status")
    failures: list[str] = []
    for field in _STATUS_FIELDS:
        for container in object_list(status.get(field)):
            waiting = object_field(object_field(container, "state"), "waiting")
            reason = string_field(waiting, "reason")
            if reason in _IMAGE_PULL_FAILURES:
                failures.append(f"{pod_name}/{string_field(container, 'name')}: {reason}")
    return tuple(failures)


class K8sImagePullFailuresCheck(HealthCheck):
    """Detect image pull failures without exposing image registry coordinates."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Inspect all pod container states for image pull failures."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        pods = await asyncio.to_thread(read_resources, platform, "pods")
        if pods is None:
            return self._make_result(CheckStatus.ERROR, "Unable to inspect Kubernetes pods")
        if not pods:
            return self._make_result(CheckStatus.FAILED, "No Kubernetes pods found")

        failures = tuple(failure for pod in pods for failure in _pull_failures(pod))
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} container(s) have image pull failures",
                details=failures,
                remediation_hint="Inspect image references and registry pull authorization for the named workloads",
            )
        return self._make_result(CheckStatus.PASSED, "No container image pull failures")

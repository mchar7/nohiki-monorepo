"""Health check for Flux Kustomization and HelmRelease convergence."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks.kubernetes._resources import (
    JsonObject,
    condition,
    conditions,
    integer_field,
    object_field,
    read_resources,
    resource_name,
    string_field,
    true_field,
)
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_KUSTOMIZATIONS: Final = "kustomizations.kustomize.toolkit.fluxcd.io"
_HELM_RELEASES: Final = "helmreleases.helm.toolkit.fluxcd.io"
_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="k8s_flux_convergence",
    name="K8s Flux Convergence",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    timeout_seconds=20.0,
    description="Validate Flux Kustomization and HelmRelease reconciliation state.",
)


def _condition_failure(kind: str, name: str, state: JsonObject | None) -> str | None:
    """Describe a non-ready condition using only logical identity and condition state."""
    if state is None:
        return f"{kind}/{name}: Ready=Missing"
    status = string_field(state, "status")
    if status == "True":
        return None
    reason = string_field(state, "reason")
    return f"{kind}/{name}: Ready={status} ({reason})"


def _flux_failures(kind: str, resources: tuple[JsonObject, ...]) -> tuple[str, ...]:
    """Return convergence invariant failures for Flux resources."""
    failures: list[str] = []
    for resource in resources:
        name = resource_name(resource)
        metadata = object_field(resource, "metadata")
        spec = object_field(resource, "spec")
        status = object_field(resource, "status")
        resource_conditions = conditions(resource)

        if true_field(spec, "suspend"):
            failures.append(f"{kind}/{name}: Suspended")

        if ready_failure := _condition_failure(kind, name, condition(resource_conditions, "Ready")):
            failures.append(ready_failure)

        generation = integer_field(metadata, "generation")
        observed_generation = integer_field(status, "observedGeneration")
        if generation is None or observed_generation is None:
            failures.append(f"{kind}/{name}: observedGeneration=Missing")
        elif observed_generation != generation:
            failures.append(f"{kind}/{name}: observedGeneration=Stale")

        stalled = condition(resource_conditions, "Stalled")
        if stalled is not None and string_field(stalled, "status") == "True":
            failures.append(f"{kind}/{name}: Stalled ({string_field(stalled, 'reason')})")
    return tuple(failures)


class K8sFluxConvergenceCheck(HealthCheck):
    """Validate that Flux controllers have converged all expected resources."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Inspect Flux resources across namespaces without exposing source revisions."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        async with asyncio.TaskGroup() as tasks:
            kustomizations_task = tasks.create_task(
                asyncio.to_thread(read_resources, platform, _KUSTOMIZATIONS, all_namespaces=True)
            )
            helm_releases_task = tasks.create_task(
                asyncio.to_thread(read_resources, platform, _HELM_RELEASES, all_namespaces=True)
            )
        kustomizations = kustomizations_task.result()
        helm_releases = helm_releases_task.result()
        if kustomizations is None or helm_releases is None:
            return self._make_result(CheckStatus.ERROR, "Unable to inspect Flux resources")

        missing = tuple(
            kind
            for kind, resources in (("Kustomization", kustomizations), ("HelmRelease", helm_releases))
            if not resources
        )
        if missing:
            return self._make_result(
                CheckStatus.FAILED,
                "Expected Flux resources are missing",
                details=tuple(f"{kind}: No resources found" for kind in missing),
            )

        failures = _flux_failures("Kustomization", kustomizations) + _flux_failures("HelmRelease", helm_releases)
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} Flux convergence invariant(s) failed",
                details=failures,
                remediation_hint="Inspect the named Flux resource conditions and reconcile its declared source",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(kustomizations) + len(helm_releases)} Flux resources converged",
        )

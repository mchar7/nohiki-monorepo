"""Health check for Gateway API control-plane readiness."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.checks.kubernetes._resources import (
    JsonObject,
    condition,
    conditions,
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

_GATEWAYS: Final = "gateways.gateway.networking.k8s.io"
_HTTP_ROUTES: Final = "httproutes.gateway.networking.k8s.io"
_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="k8s_gateway_api_readiness",
    name="K8s Gateway API Readiness",
    category=CheckCategory.KUBERNETES,
    platforms=frozenset({PlatformTarget.KUBERNETES}),
    timeout_seconds=20.0,
    description="Validate Gateway acceptance/programming and HTTPRoute references.",
)


def _required_condition_failure(
    kind: str,
    name: str,
    resource_conditions: tuple[JsonObject, ...],
    required_type: str,
    *,
    parent: int | None = None,
) -> str | None:
    """Return a redacted failure when a required Gateway API condition is not true."""
    state = condition(resource_conditions, required_type)
    identity = f"{kind}/{name}" if parent is None else f"{kind}/{name} parent {parent}"
    if state is None:
        return f"{identity}: {required_type}=Missing"
    status = string_field(state, "status")
    if status == "True":
        return None
    return f"{identity}: {required_type}={status} ({string_field(state, 'reason')})"


def _gateway_failures(gateways: tuple[JsonObject, ...]) -> tuple[str, ...]:
    """Return Gateway acceptance and programming failures."""
    failures: list[str] = []
    for gateway in gateways:
        name = resource_name(gateway)
        gateway_conditions = conditions(gateway)
        failures.extend(
            failure
            for required in ("Accepted", "Programmed")
            if (failure := _required_condition_failure("Gateway", name, gateway_conditions, required)) is not None
        )
    return tuple(failures)


def _route_failures(routes: tuple[JsonObject, ...]) -> tuple[str, ...]:
    """Return HTTPRoute parent acceptance and reference-resolution failures."""
    failures: list[str] = []
    for route in routes:
        name = resource_name(route)
        parents = object_list(object_field(route, "status").get("parents"))
        if not parents:
            failures.append(f"HTTPRoute/{name}: Parents=Missing")
            continue
        for index, parent_status in enumerate(parents, start=1):
            parent_conditions = object_list(parent_status.get("conditions"))
            failures.extend(
                failure
                for required in ("Accepted", "ResolvedRefs")
                if (
                    failure := _required_condition_failure(
                        "HTTPRoute",
                        name,
                        parent_conditions,
                        required,
                        parent=index,
                    )
                )
                is not None
            )
    return tuple(failures)


class K8sGatewayApiReadinessCheck(HealthCheck):
    """Validate Gateway API readiness without reporting listeners or addresses."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Inspect Gateway and HTTPRoute status conditions."""
        if not isinstance(platform, KubernetesPlatform):
            return self._make_result(CheckStatus.SKIPPED, "Not applicable (compose mode)")

        async with asyncio.TaskGroup() as tasks:
            gateways_task = tasks.create_task(asyncio.to_thread(read_resources, platform, _GATEWAYS))
            routes_task = tasks.create_task(asyncio.to_thread(read_resources, platform, _HTTP_ROUTES))
        gateways = gateways_task.result()
        routes = routes_task.result()
        if gateways is None or routes is None:
            return self._make_result(CheckStatus.ERROR, "Unable to inspect Gateway API resources")

        missing = tuple(kind for kind, resources in (("Gateway", gateways), ("HTTPRoute", routes)) if not resources)
        if missing:
            return self._make_result(
                CheckStatus.FAILED,
                "Expected Gateway API resources are missing",
                details=tuple(f"{kind}: No resources found" for kind in missing),
            )

        failures = _gateway_failures(gateways) + _route_failures(routes)
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} Gateway API readiness invariant(s) failed",
                details=failures,
                remediation_hint="Inspect the named Gateway API resource conditions and controller events",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(gateways)} Gateway(s) and {len(routes)} HTTPRoute(s) are ready",
        )

"""Focused tests for deployment-facing Kubernetes health checks."""

from __future__ import annotations

import json

import pytest
from health_check.checks.kubernetes._resources import JsonObject
from health_check.checks.kubernetes.flux_convergence import K8sFluxConvergenceCheck
from health_check.checks.kubernetes.gateway_api_readiness import K8sGatewayApiReadinessCheck
from health_check.checks.kubernetes.image_pull_failures import K8sImagePullFailuresCheck
from health_check.core.models import CheckStatus
from health_check.core.registry import CheckRegistry
from health_check.platform.kubernetes import KubernetesPlatform
from health_check.platform.models import PlatformTarget

from .._helpers import MockPlatform


class _ResourcePlatform(KubernetesPlatform):
    """Kubernetes adapter returning caller-supplied resource documents."""

    def __init__(self, responses: dict[str, tuple[int, str, str]]) -> None:
        super().__init__(namespace="test", local_mode=True)
        self._responses = responses
        self.calls: list[tuple[str, bool, int]] = []

    def get_resources(
        self,
        resource: str,
        *,
        all_namespaces: bool = False,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        self.calls.append((resource, all_namespaces, timeout))
        return self._responses.get(resource, (1, "", "unconfigured resource"))


def _response(*items: dict[str, object]) -> tuple[int, str, str]:
    return 0, json.dumps({"items": items}), ""


def _condition(condition_type: str, status: str = "True", reason: str = "Reconciled") -> dict[str, str]:
    return {"type": condition_type, "status": status, "reason": reason}


def _flux_resource(
    name: str,
    *,
    generation: int = 3,
    observed_generation: int = 3,
    suspended: bool = False,
    ready: str = "True",
    stalled: bool = False,
) -> dict[str, object]:
    resource_conditions: list[dict[str, str]] = [_condition("Ready", ready)]
    if stalled:
        resource_conditions.append(_condition("Stalled", reason="ReconciliationFailed"))
    return {
        "metadata": {"name": name, "generation": generation},
        "spec": {"suspend": suspended},
        "status": {"observedGeneration": observed_generation, "conditions": resource_conditions},
    }


def _gateway(name: str, *, programmed: str = "True") -> dict[str, object]:
    return {
        "metadata": {"name": name},
        "status": {
            "conditions": [
                _condition("Accepted"),
                _condition("Programmed", programmed, "AddressNotAssigned"),
            ],
            "addresses": [{"value": "192.0.2.19"}],
        },
    }


def _route(name: str, *, resolved_refs: str = "True") -> dict[str, object]:
    return {
        "metadata": {"name": name},
        "spec": {"hostnames": ["private.internal.example"]},
        "status": {
            "parents": [
                {
                    "conditions": [
                        _condition("Accepted"),
                        _condition("ResolvedRefs", resolved_refs, "BackendNotFound"),
                    ]
                }
            ]
        },
    }


def _assert_no_topology(details: tuple[str, ...]) -> None:
    rendered = "\n".join(details)
    for private_value in (
        "https://registry.internal.example:5443/team/image",
        "registry.internal.example",
        "private.internal.example",
        "192.0.2.19",
        ":5443",
        "pull-token-secret",
    ):
        assert private_value not in rendered


class TestK8sImagePullFailuresCheck:
    async def test_passes_when_pods_have_no_pull_failures(self) -> None:
        pod: JsonObject = {
            "metadata": {"name": "bff"},
            "status": {"containerStatuses": [{"name": "api", "state": {"running": {}}}]},
        }
        result = await K8sImagePullFailuresCheck().execute(_ResourcePlatform({"pods": _response(pod)}))

        assert result.status is CheckStatus.PASSED

    @pytest.mark.parametrize("reason", ["ErrImagePull", "ImagePullBackOff", "ErrImageNeverPull"])
    async def test_fails_for_each_image_pull_reason_without_registry_coordinates(self, reason: str) -> None:
        pod: JsonObject = {
            "metadata": {"name": "doc-content"},
            "status": {
                "containerStatuses": [
                    {
                        "name": "service",
                        "image": "registry.internal.example:5443/team/image",
                        "state": {
                            "waiting": {
                                "reason": reason,
                                "message": (
                                    "failed https://registry.internal.example:5443/team/image with pull-token-secret"
                                ),
                            }
                        },
                    }
                ]
            },
        }

        result = await K8sImagePullFailuresCheck().execute(_ResourcePlatform({"pods": _response(pod)}))

        assert result.status is CheckStatus.FAILED
        assert result.details == (f"doc-content/service: {reason}",)
        _assert_no_topology(result.details)

    async def test_errors_when_pods_cannot_be_inspected(self) -> None:
        result = await K8sImagePullFailuresCheck().execute(
            _ResourcePlatform({"pods": (1, "", "https://registry.internal.example:5443 failed")})
        )

        assert result.status is CheckStatus.ERROR
        _assert_no_topology(result.details)

    async def test_fails_when_no_pods_exist(self) -> None:
        result = await K8sImagePullFailuresCheck().execute(_ResourcePlatform({"pods": _response()}))

        assert result.status is CheckStatus.FAILED

    async def test_skips_compose(self) -> None:
        result = await K8sImagePullFailuresCheck().execute(MockPlatform(target=PlatformTarget.COMPOSE))

        assert result.status is CheckStatus.SKIPPED


class TestK8sFluxConvergenceCheck:
    @staticmethod
    def _platform(
        kustomizations: tuple[int, str, str],
        helm_releases: tuple[int, str, str],
    ) -> _ResourcePlatform:
        return _ResourcePlatform(
            {
                "kustomizations.kustomize.toolkit.fluxcd.io": kustomizations,
                "helmreleases.helm.toolkit.fluxcd.io": helm_releases,
            }
        )

    async def test_passes_when_generations_and_conditions_converge(self) -> None:
        platform = self._platform(
            _response(_flux_resource("platform")),
            _response(_flux_resource("applications")),
        )

        result = await K8sFluxConvergenceCheck().execute(platform)

        assert result.status is CheckStatus.PASSED
        assert all(all_namespaces for _, all_namespaces, _ in platform.calls)

    async def test_fails_for_suspension_and_generation_drift(self) -> None:
        platform = self._platform(
            _response(_flux_resource("platform", suspended=True, observed_generation=2)),
            _response(_flux_resource("applications")),
        )

        result = await K8sFluxConvergenceCheck().execute(platform)

        assert result.status is CheckStatus.FAILED
        assert "Kustomization/platform: Suspended" in result.details
        assert "Kustomization/platform: observedGeneration=Stale" in result.details
        _assert_no_topology(result.details)

    async def test_fails_for_not_ready_and_stalled_conditions(self) -> None:
        platform = self._platform(
            _response(_flux_resource("platform", ready="False", stalled=True)),
            _response(_flux_resource("applications")),
        )

        result = await K8sFluxConvergenceCheck().execute(platform)

        assert result.status is CheckStatus.FAILED
        assert any("Ready=False" in detail for detail in result.details)
        assert any("Stalled" in detail for detail in result.details)

    async def test_errors_when_either_flux_kind_cannot_be_inspected(self) -> None:
        platform = self._platform((1, "", "private.internal.example:5443"), _response(_flux_resource("apps")))

        result = await K8sFluxConvergenceCheck().execute(platform)

        assert result.status is CheckStatus.ERROR
        _assert_no_topology(result.details)

    async def test_fails_when_expected_flux_kind_is_empty(self) -> None:
        result = await K8sFluxConvergenceCheck().execute(
            self._platform(_response(), _response(_flux_resource("applications")))
        )

        assert result.status is CheckStatus.FAILED
        assert result.details == ("Kustomization: No resources found",)

    async def test_skips_compose(self) -> None:
        result = await K8sFluxConvergenceCheck().execute(MockPlatform(target=PlatformTarget.COMPOSE))

        assert result.status is CheckStatus.SKIPPED


class TestK8sGatewayApiReadinessCheck:
    @staticmethod
    def _platform(gateways: tuple[int, str, str], routes: tuple[int, str, str]) -> _ResourcePlatform:
        return _ResourcePlatform(
            {
                "gateways.gateway.networking.k8s.io": gateways,
                "httproutes.gateway.networking.k8s.io": routes,
            }
        )

    async def test_passes_when_gateway_and_route_conditions_are_true(self) -> None:
        result = await K8sGatewayApiReadinessCheck().execute(
            self._platform(_response(_gateway("public")), _response(_route("api")))
        )

        assert result.status is CheckStatus.PASSED

    async def test_fails_for_gateway_and_route_condition_violations_without_topology(self) -> None:
        result = await K8sGatewayApiReadinessCheck().execute(
            self._platform(
                _response(_gateway("public", programmed="False")),
                _response(_route("api", resolved_refs="False")),
            )
        )

        assert result.status is CheckStatus.FAILED
        assert any("Gateway/public: Programmed=False" in detail for detail in result.details)
        assert any("HTTPRoute/api parent 1: ResolvedRefs=False" in detail for detail in result.details)
        _assert_no_topology(result.details)

    async def test_fails_when_gateway_or_route_is_not_accepted(self) -> None:
        gateway: JsonObject = {
            "metadata": {"name": "public"},
            "status": {"conditions": [_condition("Accepted", "False", "Invalid"), _condition("Programmed")]},
        }
        route: JsonObject = {
            "metadata": {"name": "api"},
            "status": {
                "parents": [
                    {
                        "conditions": [
                            _condition("Accepted", "False", "NotAllowedByListeners"),
                            _condition("ResolvedRefs"),
                        ]
                    }
                ]
            },
        }

        result = await K8sGatewayApiReadinessCheck().execute(self._platform(_response(gateway), _response(route)))

        assert result.status is CheckStatus.FAILED
        assert any("Gateway/public: Accepted=False" in detail for detail in result.details)
        assert any("HTTPRoute/api parent 1: Accepted=False" in detail for detail in result.details)

    async def test_fails_when_route_has_no_parent_conditions(self) -> None:
        route: JsonObject = {"metadata": {"name": "orphaned"}, "status": {"parents": []}}

        result = await K8sGatewayApiReadinessCheck().execute(
            self._platform(_response(_gateway("public")), _response(route))
        )

        assert result.status is CheckStatus.FAILED
        assert result.details == ("HTTPRoute/orphaned: Parents=Missing",)

    async def test_errors_when_gateway_resources_cannot_be_inspected(self) -> None:
        result = await K8sGatewayApiReadinessCheck().execute(
            self._platform((0, "not-json", ""), _response(_route("api")))
        )

        assert result.status is CheckStatus.ERROR

    async def test_fails_when_gateway_or_route_set_is_empty(self) -> None:
        result = await K8sGatewayApiReadinessCheck().execute(self._platform(_response(_gateway("public")), _response()))

        assert result.status is CheckStatus.FAILED
        assert result.details == ("HTTPRoute: No resources found",)

    async def test_skips_compose(self) -> None:
        result = await K8sGatewayApiReadinessCheck().execute(MockPlatform(target=PlatformTarget.COMPOSE))

        assert result.status is CheckStatus.SKIPPED


class TestDeploymentCheckDiscovery:
    def test_new_checks_are_auto_discovered_with_expected_ids(self) -> None:
        registry = CheckRegistry()
        registry.discover()

        ids = {check.metadata.check_id for check in registry.all_checks}

        assert {
            "k8s_image_pull_failures",
            "k8s_flux_convergence",
            "k8s_gateway_api_readiness",
            "llm_workload_readiness",
            "pipeline_progress",
        } <= ids

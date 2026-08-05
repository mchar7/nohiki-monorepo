import re
import subprocess
import tarfile
from pathlib import Path
from typing import TypeIs

import pytest
import yaml
from _documents import (
    Manifest,
    containers_of,
    load_manifests,
    load_mapping,
    mapping_at,
    mapping_sequence_at,
    string_at,
)
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_CHART = _ROOT / "infra" / "k8s" / "helm"
_FOUNDATION_CHART = _ROOT / "infra" / "k8s" / "helm-foundation"
_OBSERVABILITY_OVERLAY = _ROOT / "infra" / "k8s" / "observability" / "overlays" / "staging"
_STAGING_GITOPS = _ROOT / "infra" / "k8s" / "gitops" / "clusters" / "staging-aks"
_OPERATOR_CRDS = {
    "instrumentations.opentelemetry.io",
    "opampbridges.opentelemetry.io",
    "opentelemetrycollectors.opentelemetry.io",
    "targetallocators.opentelemetry.io",
}
_PINNED_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@sha256:[0-9a-f]{64}")
_PINNED_IMAGE = re.compile(r"[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")


def _is_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> dict[str, object]:
    assert _is_mapping(value)
    return value


def _mapping_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_mapping(item) for item in value]


def _locked_operator_dependency() -> dict[str, object]:
    lock = load_mapping(_FOUNDATION_CHART / "Chart.lock")
    dependencies = mapping_sequence_at(lock, "dependencies")
    return next(item for item in dependencies if item.get("name") == "opentelemetry-operator")


def _operator_archive() -> Path:
    dependency = _locked_operator_dependency()
    name = string_at(dependency, "name")
    version = string_at(dependency, "version")
    return _FOUNDATION_CHART / "charts" / f"{name}-{version}.tgz"


def _archived_mapping(member: str) -> dict[str, object]:
    with tarfile.open(_operator_archive()) as archive:
        metadata_file = archive.extractfile(member)
        assert metadata_file is not None
        metadata: object = yaml.safe_load(metadata_file)
    return _mapping(metadata)


def _manager_image() -> str:
    defaults = _archived_mapping("opentelemetry-operator/values.yaml")
    repository = string_at(defaults, "manager", "image", "repository")
    values = load_mapping(_FOUNDATION_CHART / "values.yaml")
    tag = string_at(values, "opentelemetry-operator", "manager", "image", "tag")
    return f"{repository}:{tag}"


def _render_platform() -> tuple[Manifest, ...]:
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "-f",
        "values.yaml",
        "-f",
        "values.staging.yaml",
        "-n",
        "nohiki-staging",
    ]
    command.extend(runtime_eso_args("staging"))
    result = subprocess.run(command, cwd=_PLATFORM_CHART, capture_output=True, text=True, check=True)
    return tuple(load_manifests(result.stdout))


def _render_foundation() -> tuple[Manifest, ...]:
    result = subprocess.run(
        ["helm", "template", "foundation", ".", "--namespace", "nohiki-foundation"],
        cwd=_FOUNDATION_CHART,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(load_manifests(result.stdout))


def _render_observability() -> tuple[Manifest, ...]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(_OBSERVABILITY_OVERLAY)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return tuple(load_manifests(result.stdout))


@pytest.fixture(scope="module")
def rendered_manifests() -> dict[str, tuple[Manifest, ...]]:
    """Render each immutable manifest source once."""
    return {
        "foundation": _render_foundation(),
        "platform": _render_platform(),
        "observability": _render_observability(),
    }


def _operator_resources(documents: tuple[Manifest, ...], kind: str) -> tuple[Manifest, ...]:
    return tuple(
        document
        for document in documents
        if document["kind"] == kind
        and document["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "opentelemetry-operator"
    )


def test_foundation_owns_locked_operator_dependency_and_platform_disables_its_copy() -> None:
    foundation_chart = load_mapping(_FOUNDATION_CHART / "Chart.yaml")
    foundation_lock = load_mapping(_FOUNDATION_CHART / "Chart.lock")
    platform_values = load_mapping(_PLATFORM_CHART / "values.yaml")
    foundation_values = load_mapping(_FOUNDATION_CHART / "values.yaml")

    chart_dependencies = [
        item
        for item in mapping_sequence_at(foundation_chart, "dependencies")
        if item.get("name") == "opentelemetry-operator"
    ]
    lock_dependencies = [
        item
        for item in mapping_sequence_at(foundation_lock, "dependencies")
        if item.get("name") == "opentelemetry-operator"
    ]
    assert len(chart_dependencies) == len(lock_dependencies) == 1
    chart_dependency = chart_dependencies[0]
    lock_dependency = lock_dependencies[0]
    assert chart_dependency.get("version") == lock_dependency.get("version")
    assert chart_dependency.get("repository") == lock_dependency.get("repository")
    foundation_operator = mapping_at(foundation_values, "opentelemetry-operator")
    platform_operator = mapping_at(platform_values, "opentelemetry-operator")
    assert foundation_operator.get("enabled") is True
    assert platform_operator.get("enabled") is False

    archive_path = _operator_archive()
    assert archive_path.is_file()
    metadata = _archived_mapping("opentelemetry-operator/Chart.yaml")
    assert metadata.get("name") == lock_dependency.get("name")
    assert metadata.get("version") == lock_dependency.get("version")
    tag = string_at(foundation_operator, "manager", "image", "tag")
    assert tag.partition("@")[0] == metadata.get("appVersion")


def test_foundation_values_pin_manager_and_preserve_metric_shape() -> None:
    root_values = load_mapping(_FOUNDATION_CHART / "values.yaml")
    values = mapping_at(root_values, "opentelemetry-operator")
    manager = mapping_at(values, "manager")
    service_monitor = mapping_at(manager, "serviceMonitor")
    assert _is_mapping(manager.get("image"))
    assert _is_mapping(manager.get("featureGatesMap"))
    tag = string_at(manager, "image", "tag")
    assert _PINNED_TAG.fullmatch(tag)
    assert "featureGates" not in manager
    assert "kubeRBACProxy" not in values
    assert service_monitor.get("enabled") is False


def test_operator_renders_single_manager_with_secure_metrics(
    rendered_manifests: dict[str, tuple[Manifest, ...]],
) -> None:
    foundation = rendered_manifests["foundation"]
    platform = rendered_manifests["platform"]

    deployments = _operator_resources(foundation, "Deployment")
    assert len(deployments) == 1
    assert _operator_resources(platform, "Deployment") == ()
    deployment = deployments[0]
    metadata = deployment["metadata"]
    labels = metadata["labels"]
    assert (
        metadata["name"],
        metadata["namespace"],
        labels["app.kubernetes.io/instance"],
        labels["app.kubernetes.io/managed-by"],
    ) == (
        "foundation-opentelemetry-operator",
        "nohiki-foundation",
        "foundation",
        "Helm",
    )

    containers = containers_of(deployment)
    assert len(containers) == 1
    manager = containers[0]
    expected_manager_image = _manager_image()
    assert manager["image"] == expected_manager_image
    assert _PINNED_IMAGE.fullmatch(expected_manager_image)
    manager_args = manager.get("args")
    assert isinstance(manager_args, list)
    assert "--metrics-addr=0.0.0.0:8443" in manager_args
    assert "--metrics-secure=true" in manager_args
    assert "--feature-gates=-operator.collector.usedefaulttelemetryshape" in manager_args
    readiness_probe = manager.get("readinessProbe")
    assert isinstance(readiness_probe, dict)
    assert readiness_probe.get("httpGet") == {
        "path": "/readyz",
        "port": 8081,
    }
    assert not any("kube-rbac-proxy" in container["image"] for container in containers)

    services = _operator_resources(foundation, "Service")
    assert len(services) == 2
    metrics_services: list[Manifest] = []
    for service in services:
        ports = _mapping_list(mapping_at(service, "spec").get("ports", []))
        if any(port.get("name") == "metrics" for port in ports):
            metrics_services.append(service)
    assert len(metrics_services) == 1
    metrics_ports = mapping_sequence_at(metrics_services[0], "spec", "ports")
    metrics_port = next(port for port in metrics_ports if port.get("name") == "metrics")
    assert metrics_port == {
        "name": "metrics",
        "port": 8443,
        "protocol": "TCP",
        "targetPort": "metrics",
    }

    assert _operator_resources(foundation, "ServiceMonitor") == ()
    assert _operator_resources(platform, "ServiceMonitor") == ()


def test_operator_renders_current_collector_crd_api(
    rendered_manifests: dict[str, tuple[Manifest, ...]],
) -> None:
    foundation_crds = {
        document["metadata"]["name"]
        for document in rendered_manifests["foundation"]
        if document["kind"] == "CustomResourceDefinition" and document["metadata"]["name"].endswith(".opentelemetry.io")
    }
    platform_crds = {
        document["metadata"]["name"]
        for document in rendered_manifests["platform"]
        if document["kind"] == "CustomResourceDefinition" and document["metadata"]["name"].endswith(".opentelemetry.io")
    }
    assert foundation_crds == _OPERATOR_CRDS
    assert platform_crds == set()

    collector_crds = [
        document
        for document in rendered_manifests["foundation"]
        if document["kind"] == "CustomResourceDefinition"
        and document["metadata"]["name"] == "opentelemetrycollectors.opentelemetry.io"
    ]
    assert len(collector_crds) == 1
    collector_crd = collector_crds[0]
    assert collector_crd["apiVersion"] == "apiextensions.k8s.io/v1"
    versions: dict[str, tuple[object, object]] = {}
    for version in mapping_sequence_at(collector_crd, "spec", "versions"):
        name = version.get("name")
        assert isinstance(name, str)
        versions[name] = (version.get("served"), version.get("storage"))
    assert versions["v1beta1"][0] is True
    assert versions["v1beta1"][1] is True

    collectors = [
        document
        for document in rendered_manifests["observability"]
        if document["kind"] == "OpenTelemetryCollector" and document["metadata"]["name"] == "nohiki-collector"
    ]
    assert len(collectors) == 1
    collector = collectors[0]
    assert collector["apiVersion"] == "opentelemetry.io/v1beta1"
    assert collector["metadata"]["labels"] == {
        "app.kubernetes.io/managed-by": "kustomize",
        "app.kubernetes.io/part-of": "nohiki-observability",
    }

    infrastructure = load_mapping(_STAGING_GITOPS / "infrastructure.yaml")
    platform = load_mapping(_STAGING_GITOPS / "platform.yaml")
    observability = load_mapping(_STAGING_GITOPS / "observability.yaml")
    infrastructure_spec = mapping_at(infrastructure, "spec")
    platform_spec = mapping_at(platform, "spec")
    observability_spec = mapping_at(observability, "spec")
    assert infrastructure_spec.get("healthChecks") == [
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "name": name,
            "namespace": "flux-system",
        }
        for name in ("nohiki-foundation", "nohiki-cloudnative-pg")
    ]
    assert platform_spec.get("dependsOn") == [{"name": "infrastructure"}]
    assert observability_spec.get("dependsOn") == [{"name": "platform"}]
    assert observability_spec.get("wait") is False
    otel_health_checks: set[tuple[object, object, str, object]] = set()
    for check in mapping_sequence_at(observability_spec, "healthChecks"):
        kind = check.get("kind")
        name = check.get("name")
        if kind in {"OpenTelemetryCollector", "Deployment"} and isinstance(name, str) and "collector" in name:
            otel_health_checks.add((check.get("apiVersion"), kind, name, check.get("namespace")))
    assert otel_health_checks == {
        ("apps/v1", "Deployment", "nohiki-collector-collector", "nohiki-staging"),
        (
            "opentelemetry.io/v1beta1",
            "OpenTelemetryCollector",
            "nohiki-collector",
            "nohiki-staging",
        ),
    }

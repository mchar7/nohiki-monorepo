import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml
from _documents import (
    Manifest,
    load_manifests,
    load_mapping,
)
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM_CHART = _ROOT / "infra" / "k8s" / "helm"
_FOUNDATION_CHART = _ROOT / "infra" / "k8s" / "helm-foundation"
_OBSERVABILITY_OVERLAY = _ROOT / "infra" / "k8s" / "observability" / "overlays" / "staging"
_STAGING_GITOPS = _ROOT / "infra" / "k8s" / "gitops" / "clusters" / "staging-aks"
_ARCHIVE = _FOUNDATION_CHART / "charts" / "opentelemetry-operator-0.119.0.tgz"
_MANAGER = (
    "ghcr.io/open-telemetry/opentelemetry-operator/opentelemetry-operator:0.154.0@sha256:"
    "263699ffea0c418530b43d95dcd49a125533325a222ffac675cbbf0d63ef035b"
)
_OPERATOR_CRDS = {
    "instrumentations.opentelemetry.io",
    "opampbridges.opentelemetry.io",
    "opentelemetrycollectors.opentelemetry.io",
    "targetallocators.opentelemetry.io",
}


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

    chart_dependencies_value = foundation_chart["dependencies"]
    lock_dependencies_value = foundation_lock["dependencies"]
    assert isinstance(chart_dependencies_value, list)
    assert isinstance(lock_dependencies_value, list)
    assert all(isinstance(item, dict) for item in chart_dependencies_value)
    assert all(isinstance(item, dict) for item in lock_dependencies_value)
    chart_dependencies = [
        item
        for item in chart_dependencies_value
        if isinstance(item, dict) and item.get("name") == "opentelemetry-operator"
    ]
    lock_dependencies = [
        item
        for item in lock_dependencies_value
        if isinstance(item, dict) and item.get("name") == "opentelemetry-operator"
    ]
    assert len(chart_dependencies) == len(lock_dependencies) == 1
    assert chart_dependencies[0].get("version") == lock_dependencies[0].get("version") == "0.119.0"
    foundation_operator = foundation_values["opentelemetry-operator"]
    platform_operator = platform_values["opentelemetry-operator"]
    assert isinstance(foundation_operator, dict)
    assert isinstance(platform_operator, dict)
    assert foundation_operator.get("enabled") is True
    assert platform_operator.get("enabled") is False

    assert _ARCHIVE.is_file()
    with tarfile.open(_ARCHIVE) as archive:
        metadata_file = archive.extractfile("opentelemetry-operator/Chart.yaml")
        assert metadata_file is not None
        metadata: object = yaml.safe_load(metadata_file)
    assert isinstance(metadata, dict)
    assert metadata.get("version") == "0.119.0"
    assert metadata.get("appVersion") == "0.154.0"


def test_foundation_values_pin_manager_and_preserve_metric_shape() -> None:
    root_values = load_mapping(_FOUNDATION_CHART / "values.yaml")
    values = root_values["opentelemetry-operator"]
    assert isinstance(values, dict)
    manager = values.get("manager")
    assert isinstance(manager, dict)
    image = manager.get("image")
    feature_gates = manager.get("featureGatesMap")
    service_monitor = manager.get("serviceMonitor")
    assert isinstance(image, dict)
    assert isinstance(feature_gates, dict)
    assert isinstance(service_monitor, dict)
    assert image.get("tag") == ("0.154.0@sha256:263699ffea0c418530b43d95dcd49a125533325a222ffac675cbbf0d63ef035b")
    assert feature_gates.get("operator.collector.usedefaulttelemetryshape") is False
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

    deployment_spec = deployment["spec"]
    assert isinstance(deployment_spec, dict)
    template = deployment_spec.get("template")
    assert isinstance(template, dict)
    pod_spec = template.get("spec")
    assert isinstance(pod_spec, dict)
    containers = pod_spec.get("containers")
    assert isinstance(containers, list)
    assert len(containers) == 1
    manager = containers[0]
    assert isinstance(manager, dict)
    assert manager.get("image") == _MANAGER
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
    container_images: list[str] = []
    for container in containers:
        assert isinstance(container, dict)
        image = container.get("image", "")
        assert isinstance(image, str)
        container_images.append(image)
    assert not any("kube-rbac-proxy" in image for image in container_images)

    services = _operator_resources(foundation, "Service")
    assert len(services) == 2
    metrics_services: list[Manifest] = []
    for service in services:
        service_spec = service["spec"]
        assert isinstance(service_spec, dict)
        ports = service_spec.get("ports", [])
        assert isinstance(ports, list)
        assert all(isinstance(port, dict) for port in ports)
        if any(isinstance(port, dict) and port.get("name") == "metrics" for port in ports):
            metrics_services.append(service)
    assert len(metrics_services) == 1
    metrics_spec = metrics_services[0]["spec"]
    assert isinstance(metrics_spec, dict)
    metrics_ports = metrics_spec.get("ports")
    assert isinstance(metrics_ports, list)
    assert all(isinstance(port, dict) for port in metrics_ports)
    metrics_port = next(port for port in metrics_ports if isinstance(port, dict) and port.get("name") == "metrics")
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
    collector_spec = collector_crd["spec"]
    assert isinstance(collector_spec, dict)
    versions_value = collector_spec.get("versions")
    assert isinstance(versions_value, list)
    versions: dict[str, tuple[object, object]] = {}
    for version in versions_value:
        assert isinstance(version, dict)
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
    infrastructure_spec = infrastructure["spec"]
    platform_spec = platform["spec"]
    observability_spec = observability["spec"]
    assert isinstance(infrastructure_spec, dict)
    assert isinstance(platform_spec, dict)
    assert isinstance(observability_spec, dict)
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
    health_checks = observability_spec.get("healthChecks")
    assert isinstance(health_checks, list)
    otel_health_checks: set[tuple[object, object, str, object]] = set()
    for check in health_checks:
        assert isinstance(check, dict)
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

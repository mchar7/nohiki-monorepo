import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml
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

type Manifest = dict[str, object]


def _load(path: Path) -> Manifest:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), path
    return document


def _documents(stdout: str) -> tuple[Manifest, ...]:
    return tuple(document for document in yaml.load_all(stdout, Loader=yaml.CSafeLoader) if isinstance(document, dict))


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
    return _documents(result.stdout)


def _render_foundation() -> tuple[Manifest, ...]:
    result = subprocess.run(
        ["helm", "template", "foundation", ".", "--namespace", "nohiki-foundation"],
        cwd=_FOUNDATION_CHART,
        capture_output=True,
        text=True,
        check=True,
    )
    return _documents(result.stdout)


def _render_observability() -> tuple[Manifest, ...]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(_OBSERVABILITY_OVERLAY)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return _documents(result.stdout)


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
        if document.get("kind") == kind
        and document.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") == "opentelemetry-operator"
    )


def test_foundation_owns_locked_operator_dependency_and_platform_disables_its_copy() -> None:
    foundation_chart = _load(_FOUNDATION_CHART / "Chart.yaml")
    foundation_lock = _load(_FOUNDATION_CHART / "Chart.lock")
    platform_values = _load(_PLATFORM_CHART / "values.yaml")
    foundation_values = _load(_FOUNDATION_CHART / "values.yaml")

    chart_dependencies = [item for item in foundation_chart["dependencies"] if item["name"] == "opentelemetry-operator"]
    lock_dependencies = [item for item in foundation_lock["dependencies"] if item["name"] == "opentelemetry-operator"]
    assert len(chart_dependencies) == len(lock_dependencies) == 1
    assert chart_dependencies[0]["version"] == lock_dependencies[0]["version"] == "0.119.0"
    assert foundation_values["opentelemetry-operator"]["enabled"] is True
    assert platform_values["opentelemetry-operator"]["enabled"] is False

    assert _ARCHIVE.is_file()
    with tarfile.open(_ARCHIVE) as archive:
        metadata_file = archive.extractfile("opentelemetry-operator/Chart.yaml")
        assert metadata_file is not None
        metadata = yaml.safe_load(metadata_file)
    assert metadata["version"] == "0.119.0"
    assert metadata["appVersion"] == "0.154.0"


def test_foundation_values_pin_manager_and_preserve_metric_shape() -> None:
    values = _load(_FOUNDATION_CHART / "values.yaml")["opentelemetry-operator"]
    assert values["manager"]["image"]["tag"] == (
        "0.154.0@sha256:263699ffea0c418530b43d95dcd49a125533325a222ffac675cbbf0d63ef035b"
    )
    assert values["manager"]["featureGatesMap"]["operator.collector.usedefaulttelemetryshape"] is False
    assert "featureGates" not in values["manager"]
    assert "kubeRBACProxy" not in values
    assert values["manager"]["serviceMonitor"]["enabled"] is False


def test_operator_renders_single_manager_with_secure_metrics(
    rendered_manifests: dict[str, tuple[Manifest, ...]],
) -> None:
    foundation = rendered_manifests["foundation"]
    platform = rendered_manifests["platform"]

    deployments = _operator_resources(foundation, "Deployment")
    assert len(deployments) == 1
    assert _operator_resources(platform, "Deployment") == ()
    deployment = deployments[0]
    assert (
        deployment["metadata"]["name"],
        deployment["metadata"]["namespace"],
        deployment["metadata"]["labels"]["app.kubernetes.io/instance"],
        deployment["metadata"]["labels"]["app.kubernetes.io/managed-by"],
    ) == (
        "foundation-opentelemetry-operator",
        "nohiki-foundation",
        "foundation",
        "Helm",
    )

    containers = deployment["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    manager = containers[0]
    assert manager["image"] == _MANAGER
    assert "--metrics-addr=0.0.0.0:8443" in manager["args"]
    assert "--metrics-secure=true" in manager["args"]
    assert "--feature-gates=-operator.collector.usedefaulttelemetryshape" in manager["args"]
    assert manager["readinessProbe"]["httpGet"] == {"path": "/readyz", "port": 8081}
    assert not any("kube-rbac-proxy" in container.get("image", "") for container in containers)

    services = _operator_resources(foundation, "Service")
    assert len(services) == 2
    metrics_services = [
        service
        for service in services
        if any(port.get("name") == "metrics" for port in service["spec"].get("ports", []))
    ]
    assert len(metrics_services) == 1
    metrics_port = next(port for port in metrics_services[0]["spec"]["ports"] if port["name"] == "metrics")
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
        if document.get("kind") == "CustomResourceDefinition"
        and document.get("metadata", {}).get("name", "").endswith(".opentelemetry.io")
    }
    platform_crds = {
        document["metadata"]["name"]
        for document in rendered_manifests["platform"]
        if document.get("kind") == "CustomResourceDefinition"
        and document.get("metadata", {}).get("name", "").endswith(".opentelemetry.io")
    }
    assert foundation_crds == _OPERATOR_CRDS
    assert platform_crds == set()

    collector_crds = [
        document
        for document in rendered_manifests["foundation"]
        if document.get("kind") == "CustomResourceDefinition"
        and document.get("metadata", {}).get("name") == "opentelemetrycollectors.opentelemetry.io"
    ]
    assert len(collector_crds) == 1
    collector_crd = collector_crds[0]
    assert collector_crd["apiVersion"] == "apiextensions.k8s.io/v1"
    versions = {version["name"]: version for version in collector_crd["spec"]["versions"]}
    assert versions["v1beta1"]["served"] is True
    assert versions["v1beta1"]["storage"] is True

    collectors = [
        document
        for document in rendered_manifests["observability"]
        if document.get("kind") == "OpenTelemetryCollector"
        and document.get("metadata", {}).get("name") == "nohiki-collector"
    ]
    assert len(collectors) == 1
    collector = collectors[0]
    assert collector["apiVersion"] == "opentelemetry.io/v1beta1"
    assert collector["metadata"]["labels"] == {
        "app.kubernetes.io/managed-by": "kustomize",
        "app.kubernetes.io/part-of": "nohiki-observability",
    }

    infrastructure = _load(_STAGING_GITOPS / "infrastructure.yaml")
    platform = _load(_STAGING_GITOPS / "platform.yaml")
    observability = _load(_STAGING_GITOPS / "observability.yaml")
    assert infrastructure["spec"]["healthChecks"] == [
        {
            "apiVersion": "helm.toolkit.fluxcd.io/v2",
            "kind": "HelmRelease",
            "name": "nohiki-foundation",
            "namespace": "flux-system",
        }
    ]
    assert platform["spec"]["dependsOn"] == [{"name": "infrastructure"}]
    assert observability["spec"]["dependsOn"] == [{"name": "platform"}]
    assert observability["spec"]["wait"] is False
    otel_health_checks = {
        (check["apiVersion"], check["kind"], check["name"], check["namespace"])
        for check in observability["spec"]["healthChecks"]
        if check["kind"] in {"OpenTelemetryCollector", "Deployment"} and "collector" in check["name"]
    }
    assert otel_health_checks == {
        ("apps/v1", "Deployment", "nohiki-collector-collector", "nohiki-staging"),
        (
            "opentelemetry.io/v1beta1",
            "OpenTelemetryCollector",
            "nohiki-collector",
            "nohiki-staging",
        ),
    }

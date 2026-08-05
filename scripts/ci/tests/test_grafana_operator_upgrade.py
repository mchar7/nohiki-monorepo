from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

import pytest
import yaml
from _documents import (
    Manifest,
    containers_of,
    load_manifests,
    load_mapping,
    mapping_at,
    mapping_sequence_at,
    sequence_at,
    string_at,
)
from helm_test_utils import runtime_eso_args

if TYPE_CHECKING:
    from collections.abc import Mapping

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_OBSERVABILITY = _ROOT / "infra" / "k8s" / "observability"
_LOCAL_FLUX = _ROOT / "infra" / "k8s" / "gitops" / "clusters" / "local"
_GRAFANA_API = "grafana.integreatly.org/v1beta1"
_PINNED_IMAGE = re.compile(r"[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")
_EXPECTED = {
    "Grafana": {"nohiki-grafana"},
    "GrafanaFolder": {"nohiki"},
    "GrafanaDatasource": {"mimir", "tempo", "loki", "pyroscope"},
    "GrafanaDashboard": {
        "auth-listings-worker",
        "nohiki-overview",
        "nohiki-services",
        "nohiki-database",
        "nohiki-infrastructure",
        "nohiki-llm",
        "nohiki-providers",
        "nohiki-skill-canonicalization",
    },
}


def _is_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> dict[str, object]:
    assert _is_mapping(value)
    return value


def _dependency(document: Mapping[str, object], name: str) -> dict[str, object]:
    return next(item for item in mapping_sequence_at(document, "dependencies") if item.get("name") == name)


def _archived_mapping(dependency: Mapping[str, object], member: str) -> dict[str, object]:
    chart_name = string_at(dependency, "name")
    archive_path = _CHART / "charts" / f"{chart_name}-{string_at(dependency, 'version')}.tgz"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        stream = archive.extractfile(f"{chart_name}/{member}")
        assert stream is not None
        document: object = yaml.safe_load(stream)
    return _mapping(document)


def _operator_image() -> str:
    lock = load_mapping(_CHART / "Chart.lock")
    dependency = _dependency(lock, "grafana-operator")
    defaults = mapping_at(_archived_mapping(dependency, "values.yaml"), "image")
    values = load_mapping(_CHART / "values.yaml")
    tag = string_at(values, "grafana-operator", "image", "tag")
    return f"{string_at(defaults, 'registry')}/{string_at(defaults, 'repository')}:{tag}"


def _render(path: Path) -> list[Manifest]:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    if not shutil.which(command[0]):
        pytest.skip("kustomize or kubectl is required to render manifests")
    result = subprocess.run(
        [*command, str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return load_manifests(result.stdout)


def _kustomize(overlay: str) -> list[Manifest]:
    return _render(_OBSERVABILITY / "overlays" / overlay)


def _helm(values_file: str) -> list[Manifest]:
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "--values",
        "values.yaml",
        "--values",
        values_file,
        "--namespace",
        "nohiki",
        "--set",
        "global.environment=render-test",
        "--show-only",
        "charts/grafana-operator/templates/deployment.yaml",
    ]
    command.extend(runtime_eso_args(values_file.removeprefix("values.").removesuffix(".yaml")))
    result = subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=True)
    return load_manifests(result.stdout)


def test_grafana_operator_chart_lock_and_image_are_pinned_together() -> None:
    chart = load_mapping(_CHART / "Chart.yaml")
    lock = load_mapping(_CHART / "Chart.lock")
    values = load_mapping(_CHART / "values.yaml")

    chart_dependency = _dependency(chart, "grafana-operator")
    lock_dependency = _dependency(lock, "grafana-operator")
    assert chart_dependency["repository"] == lock_dependency["repository"]
    major, minor, _patch = string_at(lock_dependency, "version").split(".")
    assert chart_dependency["version"] == f"v{major}.{minor}.x"

    metadata = _archived_mapping(lock_dependency, "Chart.yaml")
    assert metadata["name"] == lock_dependency["name"]
    assert metadata["version"] == lock_dependency["version"]
    operator_values = mapping_at(values, "grafana-operator")
    tag = string_at(operator_values, "image", "tag")
    assert operator_values["enabled"] is True
    assert tag.partition("@")[0] == metadata["appVersion"]
    assert _PINNED_IMAGE.fullmatch(_operator_image())


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.staging.yaml"])
def test_grafana_operator_image_renders_for_local_and_staging(values_file: str) -> None:
    images = [
        container["image"]
        for document in _helm(values_file)
        if document.get("kind") == "Deployment"
        for container in containers_of(document)
        if "grafana-operator" in container["image"]
    ]
    assert images == [_operator_image()], values_file


def test_local_flux_waits_for_grafana_operator_before_custom_resources() -> None:
    observability = load_mapping(_LOCAL_FLUX / "observability.yaml")
    platform = load_mapping(_LOCAL_FLUX / "platform.yaml")

    assert string_at(observability, "metadata", "name") == "observability"
    assert string_at(observability, "spec", "path") == "./infra/k8s/observability/overlays/local"
    depends_on = mapping_sequence_at(observability, "spec", "dependsOn")
    assert {dependency["name"] for dependency in depends_on} >= {"platform"}
    assert string_at(platform, "metadata", "name") == "platform"
    assert {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "name": "nohiki",
        "namespace": "flux-system",
    } in sequence_at(platform, "spec", "healthChecks")


@pytest.mark.parametrize("overlay", ["local", "staging", "prod"])
def test_grafana_custom_resources_render_unchanged_and_selected(overlay: str) -> None:
    resources = [item for item in _kustomize(overlay) if item.get("kind") in _EXPECTED]
    actual: dict[str, set[str]] = {kind: set() for kind in _EXPECTED}

    for resource in resources:
        kind = resource["kind"]
        name = resource["metadata"]["name"]
        actual[kind].add(name)
        assert resource["apiVersion"] == _GRAFANA_API, f"{overlay}: {kind}/{name}"
        if kind != "Grafana":
            assert mapping_at(resource, "spec", "instanceSelector")["matchLabels"] == {"dashboards": "nohiki"}, (
                f"{overlay}: {kind}/{name}"
            )

    assert actual == _EXPECTED, overlay
    instance = next(item for item in resources if item["kind"] == "Grafana")
    assert instance["metadata"]["labels"]["dashboards"] == "nohiki", overlay

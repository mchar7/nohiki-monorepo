from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from helm_test_utils import runtime_eso_args

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


def _dependency(document: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in document["dependencies"] if item["name"] == name)


def _archived_mapping(dependency: dict[str, Any], member: str) -> dict[str, Any]:
    archive_path = _CHART / "charts" / f"{dependency['name']}-{dependency['version']}.tgz"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        stream = archive.extractfile(f"{dependency['name']}/{member}")
        assert stream is not None
        document: object = yaml.safe_load(stream)
    assert isinstance(document, dict)
    return document


def _operator_image() -> str:
    lock = yaml.safe_load((_CHART / "Chart.lock").read_text(encoding="utf-8"))
    dependency = _dependency(lock, "grafana-operator")
    defaults = _archived_mapping(dependency, "values.yaml")["image"]
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    tag = values["grafana-operator"]["image"]["tag"]
    return f"{defaults['registry']}/{defaults['repository']}:{tag}"


def _render(path: Path) -> list[dict[str, Any]]:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    if not shutil.which(command[0]):
        pytest.skip("kustomize or kubectl is required to render manifests")
    result = subprocess.run(
        [*command, str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if isinstance(item, dict)]


def _kustomize(overlay: str) -> list[dict[str, Any]]:
    return _render(_OBSERVABILITY / "overlays" / overlay)


def _helm(values_file: str) -> list[dict[str, Any]]:
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
    return [item for item in yaml.safe_load_all(result.stdout) if isinstance(item, dict)]


def test_grafana_operator_chart_lock_and_image_are_pinned_together() -> None:
    chart = yaml.safe_load((_CHART / "Chart.yaml").read_text(encoding="utf-8"))
    lock = yaml.safe_load((_CHART / "Chart.lock").read_text(encoding="utf-8"))
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))

    chart_dependency = _dependency(chart, "grafana-operator")
    lock_dependency = _dependency(lock, "grafana-operator")
    assert chart_dependency["repository"] == lock_dependency["repository"]
    major, minor, _patch = lock_dependency["version"].split(".")
    assert chart_dependency["version"] == f"v{major}.{minor}.x"

    metadata = _archived_mapping(lock_dependency, "Chart.yaml")
    assert metadata["name"] == lock_dependency["name"]
    assert metadata["version"] == lock_dependency["version"]
    tag = values["grafana-operator"]["image"]["tag"]
    assert values["grafana-operator"]["enabled"] is True
    assert tag.partition("@")[0] == metadata["appVersion"]
    assert _PINNED_IMAGE.fullmatch(_operator_image())


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.staging.yaml"])
def test_grafana_operator_image_renders_for_local_and_staging(values_file: str) -> None:
    images = [
        container["image"]
        for document in _helm(values_file)
        for container in document.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        if "grafana-operator" in container.get("image", "")
    ]
    assert images == [_operator_image()], values_file


def test_local_flux_waits_for_grafana_operator_before_custom_resources() -> None:
    observability = yaml.safe_load((_LOCAL_FLUX / "observability.yaml").read_text(encoding="utf-8"))
    platform = yaml.safe_load((_LOCAL_FLUX / "platform.yaml").read_text(encoding="utf-8"))

    assert observability["metadata"]["name"] == "observability"
    assert observability["spec"]["path"] == "./infra/k8s/observability/overlays/local"
    assert {dependency["name"] for dependency in observability["spec"]["dependsOn"]} >= {"platform"}
    assert platform["metadata"]["name"] == "platform"
    assert {
        "apiVersion": "helm.toolkit.fluxcd.io/v2",
        "kind": "HelmRelease",
        "name": "nohiki",
        "namespace": "flux-system",
    } in platform["spec"]["healthChecks"]


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
            assert resource["spec"]["instanceSelector"]["matchLabels"] == {"dashboards": "nohiki"}, (
                f"{overlay}: {kind}/{name}"
            )

    assert actual == _EXPECTED, overlay
    instance = next(item for item in resources if item["kind"] == "Grafana")
    assert instance["metadata"]["labels"]["dashboards"] == "nohiki", overlay

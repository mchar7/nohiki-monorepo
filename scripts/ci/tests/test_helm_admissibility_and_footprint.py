from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM = _ROOT / "infra" / "k8s" / "helm"
_FOUNDATION = _ROOT / "infra" / "k8s" / "helm-foundation"
_PERSISTENT_WORKLOAD_KINDS = {"DaemonSet", "Deployment", "StatefulSet"}


def _render(
    chart: Path,
    *,
    namespace: str,
    values: Path | None = None,
    set_values: tuple[str, ...] = (),
    include_crds: bool = False,
) -> tuple[dict, ...]:
    command = ["helm", "template", chart.name, str(chart), "--namespace", namespace]
    if values is not None:
        command.extend(("--values", str(values)))
    for value in set_values:
        command.extend(("--set", value))
    if include_crds:
        command.append("--include-crds")
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return tuple(document for document in yaml.safe_load_all(rendered) if isinstance(document, dict))


def _local_platform() -> tuple[dict, ...]:
    return _render(
        _PLATFORM,
        namespace="nohiki-local",
        values=_PLATFORM / "values.local.yaml",
    )


def _local_foundation(*, include_crds: bool = False) -> tuple[dict, ...]:
    return _render(
        _FOUNDATION,
        namespace="nohiki-foundation",
        set_values=("keda.enabled=true",),
        include_crds=include_crds,
    )


def test_local_keda_resources_are_defined_by_the_foundation_dependency() -> None:
    platform = _local_platform()
    foundation = _local_foundation(include_crds=True)
    defined_kinds = {
        document["spec"]["names"]["kind"]
        for document in foundation
        if document.get("kind") == "CustomResourceDefinition" and document.get("spec", {}).get("group") == "keda.sh"
    }
    rendered_kinds = {
        document["kind"] for document in platform if document.get("apiVersion", "").startswith("keda.sh/")
    }

    assert rendered_kinds == {"ScaledObject"}
    assert rendered_kinds <= defined_kinds
    assert not any(
        document.get("apiVersion", "").startswith("http.keda.sh/") or document.get("kind") == "HTTPInterceptorProxy"
        for document in platform
    )
    assert {
        document["metadata"]["name"]
        for document in foundation
        if document.get("kind") == "Deployment" and document["metadata"]["name"].startswith("keda-")
    } == {
        "keda-admission-webhooks",
        "keda-operator",
        "keda-operator-metrics-apiserver",
    }


def test_local_persistent_workload_containers_have_requests_and_limits() -> None:
    documents = (*_local_foundation(), *_local_platform())
    workloads = [document for document in documents if document.get("kind") in _PERSISTENT_WORKLOAD_KINDS]
    assert workloads

    missing: list[tuple[str, str, str]] = []
    for workload in workloads:
        for container in workload["spec"]["template"]["spec"].get("containers", []):
            resources = container.get("resources") or {}
            if not resources.get("requests") or not resources.get("limits"):
                missing.append((workload["kind"], workload["metadata"]["name"], container["name"]))
    assert not missing, missing

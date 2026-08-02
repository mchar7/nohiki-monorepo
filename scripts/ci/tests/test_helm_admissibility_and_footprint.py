from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_PLATFORM = _ROOT / "infra" / "k8s" / "helm"
_FOUNDATION = _ROOT / "infra" / "k8s" / "helm-foundation"
_OPERATORS = _FOUNDATION / "operators"
_KEDA = _OPERATORS / "keda"
_CNPG = _OPERATORS / "cloudnative-pg"
_PERSISTENT_WORKLOAD_KINDS = {"DaemonSet", "Deployment", "StatefulSet"}


def _render(
    chart: Path,
    *,
    namespace: str,
    values: Path | None = None,
) -> tuple[dict, ...]:
    command = ["helm", "template", chart.name, str(chart), "--namespace", namespace]
    if values is not None:
        command.extend(("--values", str(values)))
    rendered = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return tuple(document for document in yaml.safe_load_all(rendered) if isinstance(document, dict))


def _local_platform() -> tuple[dict, ...]:
    return _render(
        _PLATFORM,
        namespace="nohiki-local",
        values=_PLATFORM / "values.local.yaml",
    )


def _local_foundation() -> tuple[dict, ...]:
    return _render(
        _FOUNDATION,
        namespace="nohiki-foundation",
    )


def _local_keda() -> tuple[dict, ...]:
    return _render(
        _KEDA,
        namespace="nohiki-foundation",
    )


def _local_cnpg() -> tuple[dict, ...]:
    return _render(
        _CNPG,
        namespace="nohiki-foundation",
    )


def test_local_keda_resources_are_defined_by_the_pinned_operator_chart() -> None:
    platform = _local_platform()
    keda = _local_keda()
    defined_kinds = {
        document["spec"]["names"]["kind"]
        for document in keda
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
        for document in keda
        if document.get("kind") == "Deployment" and document["metadata"]["name"].startswith("keda-")
    } == {
        "keda-admission-webhooks",
        "keda-operator",
        "keda-operator-metrics-apiserver",
    }


def test_local_persistent_workload_containers_have_requests_and_limits() -> None:
    documents = (*_local_foundation(), *_local_keda(), *_local_cnpg(), *_local_platform())
    workloads = [document for document in documents if document.get("kind") in _PERSISTENT_WORKLOAD_KINDS]
    assert workloads

    missing: list[tuple[str, str, str]] = []
    for workload in workloads:
        for container in workload["spec"]["template"]["spec"].get("containers", []):
            resources = container.get("resources") or {}
            if not resources.get("requests") or not resources.get("limits"):
                missing.append((workload["kind"], workload["metadata"]["name"], container["name"]))
    assert not missing, missing

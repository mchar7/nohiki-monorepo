from __future__ import annotations

import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_ENVS = ("local", "staging", "prod")
_STACK_VERSION = "87.15.0"
_STACK_ARCHIVE = _CHART / "charts" / f"kube-prometheus-stack-{_STACK_VERSION}.tgz"
_OPERATOR = (
    "quay.io/prometheus-operator/prometheus-operator:v0.92.1@sha256:"
    "7d9247d2351480fc74587e24681578f815f387bafb2ee7b86a852a94c4cd3774"
)
_RELOADER = (
    "quay.io/prometheus-operator/prometheus-config-reloader:v0.92.1@sha256:"
    "74550ba3e8bf93f47bc574231090d340ae9c01d25cd11ff74799e65f9fdb9a48"
)
_WEBHOOK = (
    "ghcr.io/jkroepke/kube-webhook-certgen:1.8.4@sha256:"
    "76a2170cd0c9a7758c4ac8ac5bbe9b6f73e869a15ffb77d9f684664f7d7b96b1"
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _render(environment: str) -> list[dict[str, Any]]:
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "-f",
        "values.yaml",
        "-f",
        f"values.{environment}.yaml",
        "-n",
        "nohiki" if environment == "local" else f"nohiki-{environment}",
    ]
    command.extend(runtime_eso_args(environment))
    if environment == "prod":
        with tempfile.TemporaryDirectory() as directory:
            command.extend(
                [
                    "-f",
                    str(_digest_values(Path(directory))),
                    "-f",
                    str(_ROOT / "scripts/ci/tests/fixtures/values.prod.identity.yaml"),
                    "-f",
                    str(_ROOT / "scripts/ci/tests/fixtures/values.prod.network.yaml"),
                ]
            )
            result = subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=True)
    else:
        result = subprocess.run(command, cwd=_CHART, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _images(value: object) -> set[str]:
    if isinstance(value, dict):
        own = {value["image"]} if isinstance(value.get("image"), str) else set()
        return own | set().union(*(_images(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_images(child) for child in value))
    return set()


def _strings(value: object) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(_strings(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(_strings(child) for child in value))
    return {value} if isinstance(value, str) else set()


def _inventory(documents: list[dict[str, Any]], kind: str) -> set[str]:
    return {doc["metadata"]["name"] for doc in documents if doc.get("kind") == kind}


def test_kube_prometheus_stack_dependency_is_locked_to_87_15() -> None:
    chart = _load(_CHART / "Chart.yaml")
    lock = _load(_CHART / "Chart.lock")
    assert next(d for d in chart["dependencies"] if d["name"] == "kube-prometheus-stack")["version"] == _STACK_VERSION
    assert next(d for d in lock["dependencies"] if d["name"] == "kube-prometheus-stack")["version"] == _STACK_VERSION
    assert _STACK_ARCHIVE.is_file()


def test_operator_values_use_current_keys_and_immutable_images() -> None:
    operator = _load(_CHART / "values.yaml")["kube-prometheus-stack"]["prometheusOperator"]
    assert operator["image"] == {
        "tag": "v0.92.1",
        "sha": "7d9247d2351480fc74587e24681578f815f387bafb2ee7b86a852a94c4cd3774",
    }
    assert operator["prometheusConfigReloader"]["image"] == {
        "tag": "v0.92.1",
        "sha": "74550ba3e8bf93f47bc574231090d340ae9c01d25cd11ff74799e65f9fdb9a48",
    }
    assert operator["admissionWebhooks"]["patch"]["image"] == {
        "tag": "1.8.4",
        "sha": "76a2170cd0c9a7758c4ac8ac5bbe9b6f73e869a15ffb77d9f684664f7d7b96b1",
    }
    assert "configReloaderImage" not in operator
    assert "prometheusConfigReloaderImage" not in operator


@pytest.mark.parametrize("environment", _ENVS)
def test_stack_renders_expected_workloads_and_exact_images(environment: str) -> None:
    documents = _render(environment)
    images = _images(documents)
    assert {_OPERATOR, _WEBHOOK} <= images
    assert any(_RELOADER in value for value in _strings(documents))
    workloads = {
        (kind, name)
        for kind in ("DaemonSet", "Deployment", "Job")
        for name in _inventory(documents, kind)
        if name.startswith(
            ("nohiki-prometheus-node-exporter", "nohiki-kube-prometheus-sta", "nohiki-kube-state-metrics")
        )
    }
    assert workloads == {
        ("DaemonSet", "nohiki-prometheus-node-exporter"),
        ("Deployment", "nohiki-kube-prometheus-sta-operator"),
        ("Deployment", "nohiki-kube-state-metrics"),
        ("Job", "nohiki-kube-prometheus-sta-admission-create"),
        ("Job", "nohiki-kube-prometheus-sta-admission-patch"),
    }


def test_current_monitoring_crds_are_packaged() -> None:
    archive = _STACK_ARCHIVE
    with tarfile.open(archive) as chart:
        texts = [
            chart.extractfile(member).read().decode()
            for member in chart.getmembers()
            if member.isfile() and "/crds/crd-" in member.name and member.name.endswith(".yaml")
        ]
    by_name = {
        line.removeprefix("  name: "): text
        for text in texts
        for line in text.splitlines()
        if line.startswith("  name: ") and line.endswith(".monitoring.coreos.com")
    }
    expected = {
        "alertmanagerconfigs.monitoring.coreos.com",
        "alertmanagers.monitoring.coreos.com",
        "podmonitors.monitoring.coreos.com",
        "probes.monitoring.coreos.com",
        "prometheusagents.monitoring.coreos.com",
        "prometheuses.monitoring.coreos.com",
        "prometheusrules.monitoring.coreos.com",
        "scrapeconfigs.monitoring.coreos.com",
        "servicemonitors.monitoring.coreos.com",
        "thanosrulers.monitoring.coreos.com",
    }
    assert expected <= by_name.keys()
    for name in expected:
        assert "apiVersion: apiextensions.k8s.io/v1" in by_name[name]
        assert "name: v1" in by_name[name]
        assert "served: true" in by_name[name]
        assert "storage: true" in by_name[name]


def test_observability_contract_is_preserved_across_environments() -> None:
    base = _load(_CHART / "values.yaml")["kube-prometheus-stack"]["prometheus"]["prometheusSpec"]
    assert base["storageSpec"] == {
        "volumeClaimTemplate": {
            "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "20Gi"}}}
        }
    }
    assert base["remoteWrite"][0]["headers"] == {"X-Scope-OrgID": "nohiki"}
    assert base["remoteWrite"][0]["writeRelabelConfigs"] == [
        {"sourceLabels": ["__name__"], "regex": "go_.*", "action": "drop"}
    ]
    rendered = {environment: _render(environment) for environment in _ENVS}
    for environment, documents in rendered.items():
        prometheus = next(doc for doc in documents if doc.get("kind") == "Prometheus")
        overlay_spec = _load(_CHART / f"values.{environment}.yaml")["kube-prometheus-stack"]["prometheus"][
            "prometheusSpec"
        ]
        expected_storage = overlay_spec.get("storageSpec", base["storageSpec"])["volumeClaimTemplate"]["spec"][
            "resources"
        ]["requests"]["storage"]
        assert (
            prometheus["spec"]["storage"]["volumeClaimTemplate"]["spec"]["resources"]["requests"]["storage"]
            == expected_storage
        )
        assert prometheus["spec"]["storage"]["volumeClaimTemplate"]["spec"]["accessModes"] == ["ReadWriteOnce"]
        namespace = "nohiki" if environment == "local" else f"nohiki-{environment}"
        assert prometheus["spec"]["remoteWrite"][0]["url"] == (
            f"http://nohiki-mimir-nginx.{namespace}.svc:80/api/v1/push"
        )
    assert (
        _inventory(rendered["local"], "PrometheusRule")
        == _inventory(rendered["staging"], "PrometheusRule")
        == _inventory(rendered["prod"], "PrometheusRule")
    )
    stack_monitors = {
        environment: {
            name
            for name in _inventory(documents, "ServiceMonitor")
            if name.startswith("nohiki-kube") or name == "nohiki-prometheus-node-exporter"
        }
        for environment, documents in rendered.items()
    }
    assert stack_monitors["local"] == stack_monitors["staging"] == stack_monitors["prod"]

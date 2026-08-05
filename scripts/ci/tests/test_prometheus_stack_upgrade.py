from __future__ import annotations

import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import TypeIs

import pytest
import yaml
from _documents import Manifest, load_manifests, load_mapping, mapping_at, mapping_sequence_at, string_at
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_ENVS = ("local", "staging", "prod")
_PINNED_IMAGE = re.compile(r"[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")
_RAW_SHA256 = re.compile(r"[0-9a-f]{64}")


def _is_string_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _dependency(document: dict[str, object], name: str) -> dict[str, object]:
    dependencies = mapping_sequence_at(document, "dependencies")
    return next(item for item in dependencies if item.get("name") == name)


def _stack_archive() -> Path:
    dependency = _dependency(load_mapping(_CHART / "Chart.lock"), "kube-prometheus-stack")
    return _CHART / "charts" / f"{dependency['name']}-{dependency['version']}.tgz"


def _archived_mapping(member: str) -> dict[str, object]:
    with tarfile.open(_stack_archive()) as archive:
        stream = archive.extractfile(f"kube-prometheus-stack/{member}")
        assert stream is not None
        document: object = yaml.safe_load(stream)
    assert _is_string_mapping(document)
    return document


def _image_ref(defaults: dict[str, object], overrides: dict[str, object]) -> str:
    return f"{defaults['registry']}/{defaults['repository']}:{overrides['tag']}@sha256:{overrides['sha']}"


def _expected_stack_images() -> tuple[str, str, str]:
    defaults = mapping_at(_archived_mapping("values.yaml"), "prometheusOperator")
    operator = mapping_at(load_mapping(_CHART / "values.yaml"), "kube-prometheus-stack", "prometheusOperator")
    return (
        _image_ref(mapping_at(defaults, "image"), mapping_at(operator, "image")),
        _image_ref(
            mapping_at(defaults, "prometheusConfigReloader", "image"),
            mapping_at(operator, "prometheusConfigReloader", "image"),
        ),
        _image_ref(
            mapping_at(defaults, "admissionWebhooks", "patch", "image"),
            mapping_at(operator, "admissionWebhooks", "patch", "image"),
        ),
    )


def _render(environment: str) -> list[Manifest]:
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
    return load_manifests(result.stdout)


def _images(value: object) -> set[str]:
    images: set[str] = set()
    if isinstance(value, dict):
        image = value.get("image")
        if isinstance(image, str):
            images.add(image)
        for child in value.values():
            images.update(_images(child))
    elif isinstance(value, list):
        for child in value:
            images.update(_images(child))
    return images


def _collect_strings(value: object) -> set[str]:
    strings: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            strings.update(_collect_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.update(_collect_strings(child))
    elif isinstance(value, str):
        strings.add(value)
    return strings


def _inventory(documents: list[Manifest], kind: str) -> set[str]:
    return {document["metadata"]["name"] for document in documents if document["kind"] == kind}


def test_kube_prometheus_stack_dependency_is_locked_and_packaged() -> None:
    chart = load_mapping(_CHART / "Chart.yaml")
    lock = load_mapping(_CHART / "Chart.lock")
    chart_dependency = _dependency(chart, "kube-prometheus-stack")
    lock_dependency = _dependency(lock, "kube-prometheus-stack")
    assert chart_dependency["version"] == lock_dependency["version"]
    assert chart_dependency["repository"] == lock_dependency["repository"]

    archive = _stack_archive()
    assert archive.is_file()
    metadata = _archived_mapping("Chart.yaml")
    assert metadata["name"] == lock_dependency["name"]
    assert metadata["version"] == lock_dependency["version"]


def test_operator_values_use_current_keys_and_immutable_images() -> None:
    values = load_mapping(_CHART / "values.yaml")
    operator = mapping_at(values, "kube-prometheus-stack", "prometheusOperator")
    operator_image = mapping_at(operator, "image")
    reloader_image = mapping_at(operator, "prometheusConfigReloader", "image")
    webhook_image = mapping_at(operator, "admissionWebhooks", "patch", "image")
    for image in (operator_image, reloader_image, webhook_image):
        assert set(image) == {"tag", "sha"}
        assert isinstance(image["tag"], str)
        assert _RAW_SHA256.fullmatch(string_at(image, "sha"))
    metadata = _archived_mapping("Chart.yaml")
    assert operator_image["tag"] == metadata["appVersion"]
    assert reloader_image["tag"] == operator_image["tag"]
    assert all(_PINNED_IMAGE.fullmatch(image) for image in _expected_stack_images())
    assert "configReloaderImage" not in operator
    assert "prometheusConfigReloaderImage" not in operator


@pytest.mark.parametrize("environment", _ENVS)
def test_stack_renders_expected_workloads_and_exact_images(environment: str) -> None:
    documents = _render(environment)
    images = _images(documents)
    operator_image, reloader_image, webhook_image = _expected_stack_images()
    assert {operator_image, webhook_image} <= images
    assert any(reloader_image in value for value in _collect_strings(documents))
    workloads = {
        (kind, name)
        for kind in ("DaemonSet", "Deployment", "Job")
        for name in _inventory(documents, kind)
        if name.startswith(
            (
                "nohiki-prometheus-node-exporter",
                "nohiki-kube-prometheus-sta",
                "nohiki-kube-state-metrics",
            )
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
    archive = _stack_archive()
    with tarfile.open(archive) as chart:
        texts: list[str] = []
        for member in chart.getmembers():
            if member.isfile() and "/crds/crd-" in member.name and member.name.endswith(".yaml"):
                extracted = chart.extractfile(member)
                assert extracted is not None
                texts.append(extracted.read().decode())
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
    values = load_mapping(_CHART / "values.yaml")
    base = mapping_at(values, "kube-prometheus-stack", "prometheus", "prometheusSpec")
    base_storage_spec = mapping_at(base, "storageSpec")
    assert base_storage_spec == {
        "volumeClaimTemplate": {
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "20Gi"}},
            }
        }
    }
    remote_write = mapping_sequence_at(base, "remoteWrite")
    assert remote_write[0].get("headers") == {"X-Scope-OrgID": "nohiki"}
    assert remote_write[0].get("writeRelabelConfigs") == [
        {"sourceLabels": ["__name__"], "regex": "go_.*", "action": "drop"}
    ]
    rendered = {environment: _render(environment) for environment in _ENVS}
    for environment, documents in rendered.items():
        prometheus = next(document for document in documents if document["kind"] == "Prometheus")
        overlay_spec = mapping_at(
            load_mapping(_CHART / f"values.{environment}.yaml"),
            "kube-prometheus-stack",
            "prometheus",
            "prometheusSpec",
        )
        storage_spec = mapping_at(overlay_spec, "storageSpec") if "storageSpec" in overlay_spec else base_storage_spec
        requests = mapping_at(storage_spec, "volumeClaimTemplate", "spec", "resources", "requests")
        expected_storage = requests.get("storage")

        prometheus_spec = mapping_at(prometheus, "spec")
        rendered_claim_spec = mapping_at(prometheus_spec, "storage", "volumeClaimTemplate", "spec")
        rendered_requests = mapping_at(rendered_claim_spec, "resources", "requests")
        assert rendered_requests.get("storage") == expected_storage
        assert rendered_claim_spec.get("accessModes") == ["ReadWriteOnce"]
        namespace = "nohiki" if environment == "local" else f"nohiki-{environment}"
        rendered_remote_write = mapping_sequence_at(prometheus_spec, "remoteWrite")
        assert rendered_remote_write[0].get("url") == f"http://nohiki-mimir-nginx.{namespace}.svc:80/api/v1/push"
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

from __future__ import annotations

import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml
from _documents import Manifest, load_manifests, load_mapping
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_ENVS = ("local", "staging", "prod")
_PINNED_IMAGE = re.compile(r"[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")
_RAW_SHA256 = re.compile(r"[0-9a-f]{64}")


def _dependency(document: dict[str, object], name: str) -> dict[str, object]:
    dependencies = document["dependencies"]
    assert isinstance(dependencies, list)
    return next(item for item in dependencies if isinstance(item, dict) and item.get("name") == name)


def _stack_archive() -> Path:
    dependency = _dependency(load_mapping(_CHART / "Chart.lock"), "kube-prometheus-stack")
    return _CHART / "charts" / f"{dependency['name']}-{dependency['version']}.tgz"


def _archived_mapping(member: str) -> dict[str, object]:
    with tarfile.open(_stack_archive()) as archive:
        stream = archive.extractfile(f"kube-prometheus-stack/{member}")
        assert stream is not None
        document: object = yaml.safe_load(stream)
    assert isinstance(document, dict)
    return document


def _image_ref(defaults: object, overrides: object) -> str:
    assert isinstance(defaults, dict)
    assert isinstance(overrides, dict)
    return f"{defaults['registry']}/{defaults['repository']}:{overrides['tag']}@sha256:{overrides['sha']}"


def _expected_stack_images() -> tuple[str, str, str]:
    defaults = _archived_mapping("values.yaml")["prometheusOperator"]
    values = load_mapping(_CHART / "values.yaml")["kube-prometheus-stack"]
    assert isinstance(defaults, dict)
    assert isinstance(values, dict)
    operator = values["prometheusOperator"]
    assert isinstance(operator, dict)
    default_reloader = defaults["prometheusConfigReloader"]
    reloader = operator["prometheusConfigReloader"]
    assert isinstance(default_reloader, dict)
    assert isinstance(reloader, dict)
    default_webhooks = defaults["admissionWebhooks"]
    webhooks = operator["admissionWebhooks"]
    assert isinstance(default_webhooks, dict)
    assert isinstance(webhooks, dict)
    default_patch = default_webhooks["patch"]
    patch = webhooks["patch"]
    assert isinstance(default_patch, dict)
    assert isinstance(patch, dict)
    return (
        _image_ref(defaults["image"], operator["image"]),
        _image_ref(default_reloader["image"], reloader["image"]),
        _image_ref(default_patch["image"], patch["image"]),
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
    stack = values["kube-prometheus-stack"]
    assert isinstance(stack, dict)
    operator = stack.get("prometheusOperator")
    assert isinstance(operator, dict)
    operator_image = operator.get("image")
    assert isinstance(operator_image, dict)
    reloader = operator.get("prometheusConfigReloader")
    assert isinstance(reloader, dict)
    reloader_image = reloader.get("image")
    assert isinstance(reloader_image, dict)
    admission_webhooks = operator.get("admissionWebhooks")
    assert isinstance(admission_webhooks, dict)
    patch = admission_webhooks.get("patch")
    assert isinstance(patch, dict)
    webhook_image = patch.get("image")
    assert isinstance(webhook_image, dict)
    for image in (operator_image, reloader_image, webhook_image):
        assert set(image) == {"tag", "sha"}
        assert isinstance(image["tag"], str)
        assert isinstance(image["sha"], str)
        assert _RAW_SHA256.fullmatch(image["sha"])
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
    stack = values["kube-prometheus-stack"]
    assert isinstance(stack, dict)
    prometheus_values = stack.get("prometheus")
    assert isinstance(prometheus_values, dict)
    base = prometheus_values.get("prometheusSpec")
    assert isinstance(base, dict)
    base_storage_spec = base.get("storageSpec")
    assert base_storage_spec == {
        "volumeClaimTemplate": {
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "20Gi"}},
            }
        }
    }
    remote_write = base.get("remoteWrite")
    assert isinstance(remote_write, list)
    assert all(isinstance(item, dict) for item in remote_write)
    assert isinstance(remote_write[0], dict)
    assert remote_write[0].get("headers") == {"X-Scope-OrgID": "nohiki"}
    assert remote_write[0].get("writeRelabelConfigs") == [
        {"sourceLabels": ["__name__"], "regex": "go_.*", "action": "drop"}
    ]
    rendered = {environment: _render(environment) for environment in _ENVS}
    for environment, documents in rendered.items():
        prometheus = next(document for document in documents if document["kind"] == "Prometheus")
        overlay_values = load_mapping(_CHART / f"values.{environment}.yaml")
        overlay_stack = overlay_values["kube-prometheus-stack"]
        assert isinstance(overlay_stack, dict)
        overlay_prometheus = overlay_stack.get("prometheus")
        assert isinstance(overlay_prometheus, dict)
        overlay_spec = overlay_prometheus.get("prometheusSpec")
        assert isinstance(overlay_spec, dict)
        storage_spec = overlay_spec.get("storageSpec", base_storage_spec)
        assert isinstance(storage_spec, dict)
        volume_claim = storage_spec.get("volumeClaimTemplate")
        assert isinstance(volume_claim, dict)
        claim_spec = volume_claim.get("spec")
        assert isinstance(claim_spec, dict)
        resources = claim_spec.get("resources")
        assert isinstance(resources, dict)
        requests = resources.get("requests")
        assert isinstance(requests, dict)
        expected_storage = requests.get("storage")

        prometheus_spec = prometheus["spec"]
        assert isinstance(prometheus_spec, dict)
        rendered_storage = prometheus_spec.get("storage")
        assert isinstance(rendered_storage, dict)
        rendered_claim = rendered_storage.get("volumeClaimTemplate")
        assert isinstance(rendered_claim, dict)
        rendered_claim_spec = rendered_claim.get("spec")
        assert isinstance(rendered_claim_spec, dict)
        rendered_resources = rendered_claim_spec.get("resources")
        assert isinstance(rendered_resources, dict)
        rendered_requests = rendered_resources.get("requests")
        assert isinstance(rendered_requests, dict)
        assert rendered_requests.get("storage") == expected_storage
        assert rendered_claim_spec.get("accessModes") == ["ReadWriteOnce"]
        namespace = "nohiki" if environment == "local" else f"nohiki-{environment}"
        rendered_remote_write = prometheus_spec.get("remoteWrite")
        assert isinstance(rendered_remote_write, list)
        assert all(isinstance(item, dict) for item in rendered_remote_write)
        assert isinstance(rendered_remote_write[0], dict)
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

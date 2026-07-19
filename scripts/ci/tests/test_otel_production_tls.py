from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _names

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_OBSERVABILITY = _ROOT / "infra" / "k8s" / "observability"
_ENDPOINT = "https://nohiki-collector-collector.nohiki-prod.svc.cluster.local:4317"
_CA_PATH = "/etc/otel/ca/ca.crt"
_SERVER_DNS_NAMES = {
    "nohiki-collector-collector",
    "nohiki-collector-collector.nohiki-prod",
    "nohiki-collector-collector.nohiki-prod.svc",
    "nohiki-collector-collector.nohiki-prod.svc.cluster.local",
}
# The prod chart demands a digest for every first-party image, so track the
# build matrix rather than a hand-kept copy that silently drifts.
_IMAGE_NAMES = tuple(_names())


def _kustomize(overlay: str) -> list[dict[str, Any]]:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    if not shutil.which(command[0]):
        pytest.skip("kustomize or kubectl is required")
    result = subprocess.run(
        [*command, str(_OBSERVABILITY / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _helm(values_file: str, tmp_path: Path) -> list[dict[str, Any]]:
    chart = tmp_path / "helm"
    shutil.copytree(_CHART, chart)
    subprocess.run(
        ["helm", "package", str(chart / "charts" / "nohiki-common"), "--destination", str(chart / "charts")],
        capture_output=True,
        text=True,
        check=True,
    )
    args = [
        "helm",
        "template",
        "nohiki",
        ".",
        "--values",
        "values.yaml",
        "--values",
        values_file,
        "--namespace",
        "nohiki-prod",
    ]
    if values_file == "values.prod.yaml":
        repository = "ghcr.io/mchar7/nohiki-monorepo"
        digest_values = tmp_path / "digests.yaml"
        digest_values.write_text(
            yaml.safe_dump(
                {"global": {"imageDigests": {f"{repository}/{name}": "sha256:" + "a" * 64 for name in _IMAGE_NAMES}}}
            ),
            encoding="utf-8",
        )
        args.extend(("--values", str(digest_values)))
        args.extend(("--values", str(_ROOT / "scripts/ci/tests/fixtures/values.prod.identity.yaml")))
    args.extend(runtime_eso_args(values_file.removeprefix("values.").removesuffix(".yaml")))
    result = subprocess.run(args, cwd=chart, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def _named(documents: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(doc for doc in documents if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name)


def test_production_otel_receiver_certificate_chain_and_server_tls_render() -> None:
    documents = _kustomize("prod")
    self_signed = _named(documents, "Issuer", "otel-selfsigned")
    ca_certificate = _named(documents, "Certificate", "otel-ca")
    ca_issuer = _named(documents, "Issuer", "otel-ca")
    server_certificate = _named(documents, "Certificate", "otel-receiver")
    pki = (self_signed, ca_certificate, ca_issuer, server_certificate)
    assert all(resource["metadata"]["namespace"] == "nohiki-prod" for resource in pki)

    assert self_signed["apiVersion"] == "cert-manager.io/v1"
    assert self_signed["spec"] == {"selfSigned": {}}
    assert ca_certificate["spec"]["isCA"] is True
    assert ca_certificate["spec"]["secretName"] == "otel-ca"
    assert ca_certificate["spec"]["issuerRef"] == {
        "group": "cert-manager.io",
        "kind": "Issuer",
        "name": "otel-selfsigned",
    }
    assert ca_issuer["spec"] == {"ca": {"secretName": "otel-ca"}}
    assert server_certificate["spec"]["secretName"] == "otel-receiver-tls"
    assert server_certificate["spec"]["issuerRef"] == {"group": "cert-manager.io", "kind": "Issuer", "name": "otel-ca"}
    assert set(server_certificate["spec"]["dnsNames"]) == _SERVER_DNS_NAMES
    assert set(server_certificate["spec"]["usages"]) == {"digital signature", "key encipherment", "server auth"}

    collector = _named(documents, "OpenTelemetryCollector", "nohiki-collector")
    assert collector["spec"]["volumes"] == [{"name": "receiver-tls", "secret": {"secretName": "otel-receiver-tls"}}]
    assert collector["spec"]["volumeMounts"] == [
        {"name": "receiver-tls", "mountPath": "/etc/otel/tls", "readOnly": True}
    ]
    tls = {"cert_file": "/etc/otel/tls/tls.crt", "key_file": "/etc/otel/tls/tls.key"}
    protocols = collector["spec"]["config"]["receivers"]["otlp"]["protocols"]
    assert protocols["grpc"]["tls"] == tls
    assert protocols["http"]["tls"] == tls


@pytest.mark.parametrize("overlay", ["local", "staging"])
def test_nonproduction_otel_receivers_remain_plaintext_without_tls_secret(overlay: str) -> None:
    collector = _named(_kustomize(overlay), "OpenTelemetryCollector", "nohiki-collector")
    protocols = collector["spec"]["config"]["receivers"]["otlp"]["protocols"]
    assert "tls" not in protocols["grpc"]
    assert "tls" not in protocols["http"]
    assert not any(volume.get("name") == "receiver-tls" for volume in collector["spec"].get("volumes", []))
    assert not any(mount.get("name") == "receiver-tls" for mount in collector["spec"].get("volumeMounts", []))


def test_production_enabled_apps_mount_only_otel_ca_and_use_https(tmp_path: Path) -> None:
    documents = _helm("values.prod.yaml", tmp_path)
    checked = 0
    for workload in documents:
        if workload.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
            continue
        template = workload.get("spec", {}).get("template", {})
        containers = template.get("spec", {}).get("containers", [])
        for container in containers:
            env = {item["name"]: item.get("value") for item in container.get("env") or [] if "name" in item}
            if "OTEL_COLLECTOR_GRPC_ENDPOINT" not in env:
                continue
            checked += 1
            assert env["OTEL_COLLECTOR_GRPC_ENDPOINT"] == _ENDPOINT
            assert env["OTEL_EXPORTER_INSECURE"] == "false"
            assert env["OTEL_EXPORTER_OTLP_CERTIFICATE"] == _CA_PATH
            mount = next(item for item in container["volumeMounts"] if item["name"] == "otel-ca")
            assert mount == {"name": "otel-ca", "mountPath": "/etc/otel/ca", "readOnly": True}
            volume = next(item for item in template["spec"]["volumes"] if item["name"] == "otel-ca")
            assert volume == {
                "name": "otel-ca",
                "secret": {"secretName": "otel-receiver-tls", "items": [{"key": "ca.crt", "path": "ca.crt"}]},
            }
            assert all(item["key"] not in {"tls.key", "tls.crt"} for item in volume["secret"]["items"])
    assert checked > 0


@pytest.mark.parametrize("values_file", ["values.local.yaml", "values.staging.yaml"])
def test_nonproduction_otel_clients_remain_plaintext_without_tls_mount(values_file: str, tmp_path: Path) -> None:
    documents = _helm(values_file, tmp_path)
    checked = 0
    for workload in documents:
        template = workload.get("spec", {}).get("template", {})
        for container in template.get("spec", {}).get("containers", []):
            env = {item["name"]: item.get("value") for item in container.get("env") or [] if "name" in item}
            if "OTEL_COLLECTOR_GRPC_ENDPOINT" not in env:
                continue
            checked += 1
            assert env["OTEL_COLLECTOR_GRPC_ENDPOINT"].startswith("http://")
            assert "OTEL_EXPORTER_OTLP_CERTIFICATE" not in env
            assert not any(item.get("name") == "otel-ca" for item in container.get("volumeMounts", []))
            assert not any(item.get("name") == "otel-ca" for item in template["spec"].get("volumes", []))
    assert checked > 0

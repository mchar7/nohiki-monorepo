"""Rendered job-storage runtime configuration regressions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from test_image_digest_gitops import _digest_values

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_ROOT = _REPOSITORY_ROOT / "infra" / "compose"
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_MANIFEST = _REPOSITORY_ROOT / "data" / "config" / "semantic_representation_manifest.json"
_MANIFEST_MOUNT_PATH = "/app/data/config/semantic_representation_manifest.json"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_RFC1918_EXCEPT = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


def _compose() -> dict:
    return yaml.safe_load((_COMPOSE_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _render_helm(values_name: str, tmp_path: Path) -> tuple[dict, ...]:
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        "nohiki-prod" if values_name == "values.prod.yaml" else "nohiki-local",
        "--values",
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_values(tmp_path)),
            )
        )
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _document(documents: tuple[dict, ...], kind: str, name: str) -> dict:
    return next(
        document
        for document in reversed(documents)
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    )


def _compose_manifest_mount(service: dict) -> tuple[Path, str, bool]:
    for volume in service["volumes"]:
        if isinstance(volume, str):
            source, target, mode = volume.rsplit(":", 2)
            if target == _MANIFEST_MOUNT_PATH:
                return Path(source), target, mode == "ro"
        elif volume.get("target") == _MANIFEST_MOUNT_PATH:
            return (
                Path(volume["source"]),
                volume["target"],
                bool(volume.get("read_only")),
            )
    raise AssertionError(_MANIFEST_MOUNT_PATH)


def _env(container: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in container["env"]}


def _allows_qdrant(rule: dict, destination: dict) -> bool:
    return destination in rule.get("to", ()) and {
        "port": 6334,
        "protocol": "TCP",
    } in rule.get("ports", ())


def test_compose_job_storage_has_direct_qdrant_runtime_wiring() -> None:
    service = _compose()["services"]["nohiki-svc-job-storage"]

    source, target, read_only = _compose_manifest_mount(service)
    assert (_COMPOSE_ROOT / source).resolve() == _MANIFEST.resolve()
    assert target == _MANIFEST_MOUNT_PATH
    assert read_only is True

    expected_environment = {
        "JOB_STORAGE_QDRANT__HOST": "nohiki-infra-qdrant",
        "JOB_STORAGE_QDRANT__GRPC_PORT": "6334",
        "JOB_STORAGE_QDRANT__USE_TLS": "false",
    }
    assert {name: service["environment"][name] for name in expected_environment} == expected_environment
    assert service["depends_on"]["nohiki-infra-qdrant"] == {"condition": "service_healthy"}


@pytest.mark.parametrize(
    ("values_name", "expected_env", "qdrant_destination"),
    [
        pytest.param(
            "values.local.yaml",
            {
                "JOB_STORAGE_MANIFEST_PATH": _MANIFEST_MOUNT_PATH,
                "JOB_STORAGE_QDRANT__HOST": "nohiki-qdrant",
                "JOB_STORAGE_QDRANT__GRPC_PORT": "6334",
                "JOB_STORAGE_QDRANT__USE_TLS": "false",
            },
            {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "qdrant"}}},
            id="local",
        ),
        pytest.param(
            "values.prod.yaml",
            {
                "JOB_STORAGE_MANIFEST_PATH": _MANIFEST_MOUNT_PATH,
                "JOB_STORAGE_QDRANT__HOST": "nohiki-prod-qdrant.qdrant.cloud",
                "JOB_STORAGE_QDRANT__GRPC_PORT": "6334",
                "JOB_STORAGE_QDRANT__USE_TLS": "true",
            },
            {"ipBlock": {"cidr": "0.0.0.0/0", "except": _RFC1918_EXCEPT}},
            id="prod",
        ),
    ],
)
def test_helm_job_storage_has_direct_qdrant_runtime_wiring(
    values_name: str,
    expected_env: dict[str, str],
    qdrant_destination: dict,
    tmp_path: Path,
) -> None:
    documents = _render_helm(values_name, tmp_path)
    deployment = _document(documents, "Deployment", "nohiki-job-storage-service")
    pod_spec = deployment["spec"]["template"]["spec"]
    container = next(item for item in pod_spec["containers"] if item["name"] == "job-storage-service")

    manifest_mount = next(item for item in container["volumeMounts"] if item["name"] == "ml-manifest")
    assert manifest_mount == {
        "name": "ml-manifest",
        "mountPath": _MANIFEST_MOUNT_PATH,
        "subPath": "semantic_representation_manifest.json",
        "readOnly": True,
    }
    manifest_volume = next(item for item in pod_spec["volumes"] if item["name"] == "ml-manifest")
    assert manifest_volume == {
        "name": "ml-manifest",
        "configMap": {"name": "nohiki-ml-manifest"},
    }

    environment = _env(container)
    assert {name: environment[name]["value"] for name in expected_env} == expected_env

    policy = _document(documents, "NetworkPolicy", "nohiki-job-storage-service")
    assert any(_allows_qdrant(rule, qdrant_destination) for rule in policy["spec"]["egress"])

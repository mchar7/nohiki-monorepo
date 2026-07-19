"""Rendered user-pref direct Qdrant runtime configuration regressions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from test_image_digest_gitops import _digest_values

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_ROOT = _REPOSITORY_ROOT / "infra" / "compose"
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_MANIFEST = _REPOSITORY_ROOT / "data" / "config" / "semantic_representation_manifest.json"
_MANIFEST_MOUNT_PATH = "/app/data/config/semantic_representation_manifest.json"


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
    result = subprocess.run(command, check=True, capture_output=True, text=True)
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


def test_compose_user_pref_has_direct_qdrant_runtime_wiring() -> None:
    service = _compose()["services"]["nohiki-svc-user-pref"]
    source, target, read_only = _compose_manifest_mount(service)
    assert (_COMPOSE_ROOT / source).resolve() == _MANIFEST.resolve()
    assert target == _MANIFEST_MOUNT_PATH
    assert read_only is True
    expected_environment = {
        "USER_PREF_MANIFEST_PATH": _MANIFEST_MOUNT_PATH,
        "USER_PREF_QDRANT__HOST": "nohiki-infra-qdrant",
        "USER_PREF_QDRANT__GRPC_PORT": "6334",
        "USER_PREF_QDRANT__USE_TLS": "false",
    }
    assert {name: service["environment"][name] for name in expected_environment} == expected_environment
    assert service["depends_on"]["nohiki-infra-qdrant"] == {"condition": "service_healthy"}


@pytest.mark.parametrize(
    ("values_name", "expected_host", "expected_tls", "destination"),
    [
        (
            "values.local.yaml",
            "nohiki-qdrant",
            "false",
            {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "qdrant"}}},
        ),
        (
            "values.prod.yaml",
            "nohiki-prod-qdrant.qdrant.cloud",
            "true",
            {
                "ipBlock": {
                    "cidr": "0.0.0.0/0",
                    "except": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
                }
            },
        ),
    ],
)
def test_helm_user_pref_has_direct_qdrant_runtime_wiring(
    values_name: str,
    expected_host: str,
    expected_tls: str,
    destination: dict,
    tmp_path: Path,
) -> None:
    documents = _render_helm(values_name, tmp_path)
    deployment = _document(documents, "Deployment", "nohiki-user-pref-service")
    pod_spec = deployment["spec"]["template"]["spec"]
    container = next(item for item in pod_spec["containers"] if item["name"] == "user-pref-service")
    assert next(item for item in container["volumeMounts"] if item["name"] == "ml-manifest") == {
        "name": "ml-manifest",
        "mountPath": _MANIFEST_MOUNT_PATH,
        "subPath": "semantic_representation_manifest.json",
        "readOnly": True,
    }
    assert next(item for item in pod_spec["volumes"] if item["name"] == "ml-manifest") == {
        "name": "ml-manifest",
        "configMap": {"name": "nohiki-ml-manifest"},
    }
    environment = _env(container)
    expected = {
        "USER_PREF_MANIFEST_PATH": _MANIFEST_MOUNT_PATH,
        "USER_PREF_QDRANT__HOST": expected_host,
        "USER_PREF_QDRANT__GRPC_PORT": "6334",
        "USER_PREF_QDRANT__USE_TLS": expected_tls,
    }
    assert {name: environment[name]["value"] for name in expected} == expected
    policy = _document(documents, "NetworkPolicy", "nohiki-user-pref-service")
    assert any(
        destination in rule.get("to", ()) and {"port": 6334, "protocol": "TCP"} in rule.get("ports", ())
        for rule in policy["spec"]["egress"]
    )

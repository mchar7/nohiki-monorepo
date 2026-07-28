from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import yaml
from _documents import (
    Container,
    containers_of,
    load_manifests,
    load_mapping,
    metadata_of,
    string_at,
)

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_MIMIR_ARCHIVE = _CHART / "charts" / "mimir-distributed-6.1.0.tgz"
_ROLLOUT_CHART_METADATA = "mimir-distributed/charts/rollout-operator/Chart.yaml"
_DIGEST = "sha256:0050002aaf07a867a3a3c2aa029dc29ff2e12eb8608f1f47e4c1d307bbdfea39"


def _rollout_chart_app_version() -> str:
    with tarfile.open(_MIMIR_ARCHIVE, mode="r:gz") as archive:
        metadata_file = archive.extractfile(_ROLLOUT_CHART_METADATA)
        assert metadata_file is not None
        metadata: object = yaml.safe_load(metadata_file)
    assert isinstance(metadata, dict)
    app_version = metadata.get("appVersion")
    assert isinstance(app_version, str)
    return app_version


def _render_rollout_container() -> Container:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            ".",
            "-f",
            "values.yaml",
            "-f",
            "values.local.yaml",
            "-n",
            "nohiki",
        ],
        cwd=_CHART,
        capture_output=True,
        text=True,
        check=True,
    )
    deployments = [
        manifest
        for manifest in load_manifests(result.stdout)
        if manifest["kind"] == "Deployment" and metadata_of(manifest)["name"] == "nohiki-rollout-operator"
    ]
    assert len(deployments) == 1
    rollout_containers = [
        container for container in containers_of(deployments[0]) if container["name"] == "rollout-operator"
    ]
    assert len(rollout_containers) == 1
    return rollout_containers[0]


def test_rollout_operator_image_and_args_match_nested_chart_contract() -> None:
    app_version = _rollout_chart_app_version()
    image_tag = string_at(
        load_mapping(_CHART / "values.yaml"),
        "mimir-distributed",
        "rollout_operator",
        "image",
        "tag",
    )

    assert app_version == "v0.38.0"
    assert image_tag == f"{app_version}@{_DIGEST}"

    container = _render_rollout_container()
    assert container["image"] == f"docker.io/grafana/rollout-operator:{image_tag}"
    assert set(container["args"]) == {
        "-kubernetes.namespace=nohiki",
        "-zpdb.pod-ready-annotation-patch-timeout=5s",
        "-server-tls.enabled=true",
        "-server-tls.self-signed-cert.secret-name=certificate",
        "-server-tls.self-signed-cert.dns-name=nohiki-rollout-operator.nohiki.svc",
    }

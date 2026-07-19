from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path
from typing import Any, cast

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_MIMIR_ARCHIVE = _CHART / "charts" / "mimir-distributed-6.1.0.tgz"
_ROLLOUT_CHART_METADATA = "mimir-distributed/charts/rollout-operator/Chart.yaml"
_DIGEST = "sha256:0050002aaf07a867a3a3c2aa029dc29ff2e12eb8608f1f47e4c1d307bbdfea39"


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return cast(dict[str, Any], document)


def _rollout_chart_app_version() -> str:
    with tarfile.open(_MIMIR_ARCHIVE, mode="r:gz") as archive:
        metadata_file = archive.extractfile(_ROLLOUT_CHART_METADATA)
        assert metadata_file is not None
        metadata = yaml.safe_load(metadata_file)
    assert isinstance(metadata, dict)
    app_version = metadata.get("appVersion")
    assert isinstance(app_version, str)
    return app_version


def _render_rollout_container() -> dict[str, Any]:
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
        document
        for document in yaml.safe_load_all(result.stdout)
        if isinstance(document, dict)
        and document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "nohiki-rollout-operator"
    ]
    assert len(deployments) == 1
    containers = deployments[0]["spec"]["template"]["spec"]["containers"]
    rollout_containers = [container for container in containers if container.get("name") == "rollout-operator"]
    assert len(rollout_containers) == 1
    return cast(dict[str, Any], rollout_containers[0])


def test_rollout_operator_image_and_args_match_nested_chart_contract() -> None:
    app_version = _rollout_chart_app_version()
    image_tag = _load_yaml(_CHART / "values.yaml")["mimir-distributed"]["rollout_operator"]["image"]["tag"]

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

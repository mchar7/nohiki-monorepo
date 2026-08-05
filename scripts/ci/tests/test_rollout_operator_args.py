from __future__ import annotations

import re
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
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_ROLLOUT_CHART = "rollout-operator"
_PINNED_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@sha256:[0-9a-f]{64}")
_PINNED_IMAGE = re.compile(r"[A-Za-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")


def _mimir_dependency() -> dict[str, object]:
    lock = load_mapping(_CHART / "Chart.lock")
    dependencies = lock["dependencies"]
    assert isinstance(dependencies, list)
    return next(item for item in dependencies if isinstance(item, dict) and item.get("name") == "mimir-distributed")


def _archived_mapping(member: str) -> dict[str, object]:
    dependency = _mimir_dependency()
    archive_path = _CHART / "charts" / f"{dependency['name']}-{dependency['version']}.tgz"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        metadata_file = archive.extractfile(f"{dependency['name']}/charts/{_ROLLOUT_CHART}/{member}")
        assert metadata_file is not None
        metadata: object = yaml.safe_load(metadata_file)
    assert isinstance(metadata, dict)
    return metadata


def _rollout_chart_app_version() -> str:
    metadata = _archived_mapping("Chart.yaml")
    app_version = metadata.get("appVersion")
    assert isinstance(app_version, str)
    return app_version


def _rollout_image(image_tag: str) -> str:
    defaults = _archived_mapping("values.yaml")["image"]
    assert isinstance(defaults, dict)
    root_values = load_mapping(_CHART / "values.yaml")
    mimir_values = root_values["mimir-distributed"]
    assert isinstance(mimir_values, dict)
    rollout_values = mimir_values["rollout_operator"]
    assert isinstance(rollout_values, dict)
    image_values = rollout_values["image"]
    assert isinstance(image_values, dict)
    registry = image_values.get("registry", defaults["registry"])
    repository = image_values.get("repository", defaults["repository"])
    return f"{registry}/{repository}:{image_tag}"


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
            "values.dev.yaml",
            "-n",
            "nohiki-dev",
            *runtime_eso_args("dev"),
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

    assert _PINNED_TAG.fullmatch(image_tag)
    assert image_tag.partition("@")[0] == app_version
    local_values = load_mapping(_CHART / "values.local.yaml")
    local_mimir = local_values.get("mimir-distributed")
    assert isinstance(local_mimir, dict)
    local_rollout_operator = local_mimir.get("rollout_operator")
    assert isinstance(local_rollout_operator, dict)
    assert local_rollout_operator.get("enabled") is False

    container = _render_rollout_container()
    expected_image = _rollout_image(image_tag)
    assert _PINNED_IMAGE.fullmatch(expected_image)
    assert container["image"] == expected_image
    assert set(container["args"]) == {
        "-kubernetes.namespace=nohiki-dev",
        "-zpdb.pod-ready-annotation-patch-timeout=5s",
        "-server-tls.enabled=true",
        "-server-tls.self-signed-cert.secret-name=certificate",
        "-server-tls.self-signed-cert.dns-name=nohiki-rollout-operator.nohiki-dev.svc",
    }

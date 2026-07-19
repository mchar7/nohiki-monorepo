from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values, _names

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_DIGEST = "sha256:" + "a" * 64


def _expected_prod_image(name: str) -> str:
    # _digest_values keys each first-party repo to sha256:{build-matrix index + 1};
    # deriving the index tracks matrix reorders instead of pinning a shifted number.
    return f"ghcr.io/mchar7/nohiki-monorepo/{name}@sha256:{_names().index(name) + 1:064x}"


def _render(values_file: str, tmp_path: Path, *extra_args: str) -> list[dict[str, Any]]:
    command = [
        "helm",
        "template",
        "nohiki",
        ".",
        "--values",
        "values.yaml",
        "--values",
        values_file,
        "--namespace",
        "nohiki",
    ]
    if values_file == "values.prod.yaml":
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
    command.extend(runtime_eso_args(values_file.removeprefix("values.").removesuffix(".yaml")))
    command.extend(extra_args)
    result = subprocess.run(
        command,
        cwd=_CHART,
        capture_output=True,
        text=True,
        check=True,
    )
    return [document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict)]


def _workload(documents: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(
        document
        for document in documents
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    )


def _pod_spec(workload: dict[str, Any]) -> dict[str, Any]:
    template = (
        workload["spec"]["jobTemplate"]["spec"]["template"]
        if workload["kind"] == "CronJob"
        else workload["spec"]["template"]
    )
    return template["spec"]


def _images(value: object) -> list[str]:
    images: list[str] = []
    if isinstance(value, dict):
        image = value.get("image")
        if isinstance(image, str):
            images.append(image)
        for child in value.values():
            images.extend(_images(child))
    elif isinstance(value, list):
        for child in value:
            images.extend(_images(child))
    return images


@pytest.mark.parametrize(
    ("values_file", "service_image", "service_policy", "job_image", "job_policy"),
    [
        (
            "values.local.yaml",
            "localhost:5000/user-auth-service:dev",
            "Always",
            "localhost:5000/sys-tick-job:dev",
            "Always",
        ),
        (
            "values.staging.yaml",
            "ghcr.io/mchar7/nohiki-monorepo/user-auth-service:sha-933dda3",
            "IfNotPresent",
            "ghcr.io/mchar7/nohiki-monorepo/sys-tick-job:sha-933dda3",
            "IfNotPresent",
        ),
        (
            "values.prod.yaml",
            _expected_prod_image("user-auth-service"),
            "IfNotPresent",
            _expected_prod_image("sys-tick-job"),
            "IfNotPresent",
        ),
    ],
)
def test_first_party_service_and_job_images_preserve_environment_construction(
    values_file: str,
    service_image: str,
    service_policy: str,
    job_image: str,
    job_policy: str,
    tmp_path: Path,
) -> None:
    documents = _render(values_file, tmp_path)
    deployment = _workload(documents, "Deployment", "nohiki-user-auth-service")
    cronjob = _workload(documents, "CronJob", "nohiki-schedule-tick-publisher")

    service_container = _pod_spec(deployment)["containers"][0]
    job_container = _pod_spec(cronjob)["containers"][0]
    assert (service_container["image"], service_container["imagePullPolicy"]) == (
        service_image,
        service_policy,
    )
    assert (job_container["image"], job_container["imagePullPolicy"]) == (job_image, job_policy)


def test_first_party_service_and_job_helpers_still_resolve_digests(tmp_path: Path) -> None:
    repositories = (
        "ghcr.io/mchar7/nohiki-monorepo/user-auth-service",
        "ghcr.io/mchar7/nohiki-monorepo/sys-tick-job",
    )
    digest_values = tmp_path / "digests.yaml"
    digest_values.write_text(
        yaml.safe_dump({"global": {"imageDigests": dict.fromkeys(repositories, _DIGEST)}}),
        encoding="utf-8",
    )

    documents = _render("values.prod.yaml", tmp_path, "--values", str(digest_values))
    deployment = _workload(documents, "Deployment", "nohiki-user-auth-service")
    cronjob = _workload(documents, "CronJob", "nohiki-schedule-tick-publisher")

    assert _pod_spec(deployment)["containers"][0]["image"] == f"{repositories[0]}@{_DIGEST}"
    assert _pod_spec(cronjob)["containers"][0]["image"] == f"{repositories[1]}@{_DIGEST}"


def test_reserved_global_image_is_absent_and_dependencies_keep_their_registries(tmp_path: Path) -> None:
    base_and_local = {"values.yaml", "values.local.yaml"}
    for values_file in ("values.yaml", "values.local.yaml", "values.staging.yaml", "values.prod.yaml"):
        values = yaml.safe_load((_CHART / values_file).read_text(encoding="utf-8"))
        assert "image" not in values["global"], values_file
        # Base and local carry the canonical global.nohikiImage default; environment overlays
        # (staging, prod) inherit it rather than redeclaring, so the registry has one source of truth.
        declares = "nohikiImage" in values["global"]
        if values_file in base_and_local:
            assert declares, f"{values_file} must declare the canonical global.nohikiImage default"
        else:
            assert not declares, f"{values_file} must inherit global.nohikiImage, not redeclare it"

    production_images = _images(_render("values.prod.yaml", tmp_path))
    assert any(image.startswith("docker.io/grafana/mimir:") for image in production_images)
    assert any(image.startswith("docker.io/grafana/tempo:") for image in production_images)
    assert not any(image.startswith("ghcr.io/docker.io/") for image in production_images)
    assert not any(image.startswith("ghcr.io/grafana/mimir:") for image in production_images)
    assert not any(image.startswith("ghcr.io/grafana/tempo:") for image in production_images)


def test_mimir_storage_backend_does_not_bundle_unneeded_minio(tmp_path: Path) -> None:
    production_values = yaml.safe_load((_CHART / "values.prod.yaml").read_text(encoding="utf-8"))
    mimir_values = production_values["mimir-distributed"]
    assert mimir_values["mimir"]["structuredConfig"]["common"]["storage"]["backend"] == "azure"
    assert mimir_values["minio"]["enabled"] is False

    production_documents = _render("values.prod.yaml", tmp_path)
    assert not any("minio" in image.lower() for image in _images(production_documents))
    assert not any("minio" in document.get("metadata", {}).get("name", "").lower() for document in production_documents)

    local_values = yaml.safe_load((_CHART / "values.local.yaml").read_text(encoding="utf-8"))
    assert local_values["mimir-distributed"]["minio"]["enabled"] is False


def test_local_registry_has_a_single_source_of_truth(tmp_path: Path) -> None:
    raw = (_CHART / "values.local.yaml").read_text(encoding="utf-8")
    registry = yaml.safe_load(raw)["global"]["nohikiImage"]["registry"]
    assert registry, "global.nohikiImage.registry must carry the local registry endpoint"

    # The endpoint literal is declared once and shared by anchor alias, so the publish
    # path and the rendered pull path cannot drift onto different registries.
    assert raw.count(registry) == 1, (
        f"registry endpoint {registry!r} is declared more than once; "
        "share the single anchor instead of repeating per-workload literals"
    )

    # A first-party service and a first-party job both render against that one registry.
    documents = _render("values.local.yaml", tmp_path)
    for kind, name in (
        ("Deployment", "nohiki-user-auth-service"),
        ("CronJob", "nohiki-schedule-tick-publisher"),
    ):
        image = _pod_spec(_workload(documents, kind, name))["containers"][0]["image"]
        assert image.startswith(f"{registry}/"), image

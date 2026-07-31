from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from _documents import Manifest, load_manifests, load_mapping
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION_TAG = re.compile(r"^v?[0-9][A-Za-z0-9_.-]{0,126}$")
_PINNED_TAG = re.compile(r"^v?[0-9][A-Za-z0-9_.-]{0,126}@sha256:[0-9a-f]{64}$")
_FIRST_PARTY_IMAGE_NAMES = (
    "user-auth-service",
    "user-pref-service",
    "user-upload-service",
    "user-entitlement-service",
    "job-storage-service",
    "job-ingest-discovery-service",
    "job-ingest-schedule-service",
    "job-ingest-enrichment-service",
    "job-query-composition-service",
    "job-correlation-evaluation-service",
    "skill-graph-service",
    "doc-template-service",
    "doc-content-service",
    "doc-process-service",
    "notification-service",
    "bff-service",
    "ml-gateway-service",
    "ml-compute-service",
    "sys-tick-job",
    "snapshot-refresh-job",
    "qdrant-init",
    "kafka-connect",
)

_EXPECTED_IMAGES = {
    "docker.io/grafana/alloy@sha256:f94b1c82957accb77cd11385fd5e3600758ef1b1ab79557c97319ad28590735a",
    "docker.io/grafana/loki:3.6.12@sha256:2483b71b28b15dee230f85512cae2b20c4b5f6e98a6eabe686cbccfa5ea3ba4a",
    "docker.io/grafana/loki-canary:3.6.12@sha256:1e9bfcff38679ecf9de4e3492050c81b6c64e64421ac13d9a4f936b7d1836179",
    "docker.io/grafana/mimir:3.1.2@sha256:39cc23910bbaa60d0280fd162265a22c39120ff61b02bc993f3fd3701fb8606d",
    "docker.io/grafana/pyroscope:2.1.1@sha256:c8ad9891fc8562c794c946883c8324b7e48f4eda58d243387c7b6254f9f061fb",
    "docker.io/grafana/tempo:2.9.3@sha256:0d355cc7d9d23f93641a999fd9432084acf647f7731c732ed80f7b9a122ec85b",
    "docker.io/kiwigrid/k8s-sidecar:1.30.9@sha256:8c06e1ba643a4625de14b2db65c356f5db6b1482a25fce4754380a2936207338",
    "docker.io/memcached:1.6.45-alpine@sha256:c29847751abb41f4c268c84fb3087fee05d4edcbda44409ccb5086e26148e8a7",
    "docker.io/nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6",
    "docker.io/prom/memcached-exporter:v0.15.5@sha256:92a6ad5a3d3e2dffc75efd4e18d1470fa5703dd79b6bace53fe11312b634578e",
    "quay.io/prometheus-operator/prometheus-config-reloader@sha256:959d47672fbff2776a04ec62b8afcec89e8c036af84dc5fade50019dab212746",
}
_UPGRADED_IMAGE_COUNTS = {
    "docker.io/grafana/loki:3.6.12@sha256:2483b71b28b15dee230f85512cae2b20c4b5f6e98a6eabe686cbccfa5ea3ba4a": 3,
    "docker.io/grafana/loki-canary:3.6.12@sha256:1e9bfcff38679ecf9de4e3492050c81b6c64e64421ac13d9a4f936b7d1836179": 1,
    "docker.io/grafana/mimir:3.1.2@sha256:39cc23910bbaa60d0280fd162265a22c39120ff61b02bc993f3fd3701fb8606d": 15,
    "docker.io/grafana/tempo:2.9.3@sha256:0d355cc7d9d23f93641a999fd9432084acf647f7731c732ed80f7b9a122ec85b": 5,
    "docker.io/memcached:1.6.45-alpine@sha256:c29847751abb41f4c268c84fb3087fee05d4edcbda44409ccb5086e26148e8a7": 3,
    "docker.io/prom/memcached-exporter:v0.15.5@sha256:92a6ad5a3d3e2dffc75efd4e18d1470fa5703dd79b6bace53fe11312b634578e": 2,  # noqa: E501
}
_EXPECTED_SCAN_FINDINGS = {
    "loki": (1, 0),
    "loki-canary": (1, 0),
    "tempo": (4, 0),
    "mimir": (1, 0),
    "memcached": (0, 0),
    "memcached-exporter": (25, 1),
}
_DIGESTS = {image.partition("@")[2] for image in _EXPECTED_IMAGES}
_REPOSITORIES = {re.sub(r":[^/]+$", "", image.partition("@")[0]) for image in _EXPECTED_IMAGES}
_FORBIDDEN_PREFIXES = (
    "ghcr.io/memcached",
    "ghcr.io/nginxinc",
    "ghcr.io/prom/",
    "ghcr.io/grafana/loki",
    "ghcr.io/grafana/alloy",
)


def _image_pin_is_unambiguous(image: object) -> bool:
    if not isinstance(image, Mapping):
        return False
    tag = image.get("tag")
    digest = image.get("digest")
    if not isinstance(tag, str):
        return False
    if digest is None:
        return _PINNED_TAG.fullmatch(tag) is not None
    return isinstance(digest, str) and _VERSION_TAG.fullmatch(tag) is not None and _DIGEST.fullmatch(digest) is not None


def _render(values_file: str, tmp_path: Path | None = None) -> list[Manifest]:
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
        assert tmp_path is not None
        digest_values = _digest_values(tmp_path)
        command.extend(
            [
                "--values",
                str(Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"),
                "--values",
                str(Path(__file__).parent / "fixtures" / "values.prod.network.yaml"),
                "--values",
                str(digest_values),
            ]
        )
    command.extend(runtime_eso_args(values_file.removeprefix("values.").removesuffix(".yaml")))
    result = subprocess.run(
        command,
        cwd=_CHART,
        capture_output=True,
        text=True,
        check=True,
    )
    return load_manifests(result.stdout)


def _container_images(value: object) -> list[str]:
    images: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"containers", "initContainers"} and isinstance(child, list):
                images.extend(
                    image
                    for container in child
                    if isinstance(container, dict)
                    if isinstance(image := container.get("image"), str)
                )
            else:
                images.extend(_container_images(child))
    elif isinstance(value, list):
        for child in value:
            images.extend(_container_images(child))
    return images


@pytest.mark.parametrize(
    "values_file",
    ["values.local.yaml", "values.staging.yaml", "values.prod.yaml"],
)
def test_observability_images_use_exact_refs_and_workload_counts(values_file: str, tmp_path: Path) -> None:
    documents = _render(values_file, tmp_path)
    rendered_images = _container_images(documents)
    affected = [image for image in rendered_images if image.partition("@")[2] in _DIGESTS]

    assert documents
    assert all("apiVersion" in document and "kind" in document for document in documents)
    assert set(affected) == _EXPECTED_IMAGES
    assert not any(image.startswith(_FORBIDDEN_PREFIXES) for image in rendered_images)
    actual_counts = {image: rendered_images.count(image) for image in _UPGRADED_IMAGE_COUNTS}
    assert actual_counts == _UPGRADED_IMAGE_COUNTS

    by_repository: dict[str, set[str]] = {}
    for image in affected:
        repository, separator, digest = image.partition("@")
        assert separator, image
        assert _DIGEST.fullmatch(digest), image
        by_repository.setdefault(repository.partition(":")[0], set()).add(image)

    assert set(by_repository) == _REPOSITORIES
    assert all(len(refs) == 1 for refs in by_repository.values())


def test_observability_values_use_one_digest_mechanism_per_image() -> None:
    values = load_mapping(_CHART / "values.yaml")
    match values:
        case {
            "pyroscope": {
                "alloy": {
                    "image": dict() as alloy_image,
                    "configReloader": {"image": dict() as config_reloader_image},
                }
            }
        }:
            pass
        case _:
            pytest.fail("observability values must contain the Alloy image settings")

    assert _image_pin_is_unambiguous(alloy_image)
    assert _image_pin_is_unambiguous(config_reloader_image)


def _opentelemetry_test_framework_image(path: Path) -> Mapping[str, object]:
    values = load_mapping(path)
    match values:
        case {"opentelemetry-operator": {"testFramework": {"image": dict() as image}}}:
            return {str(key): value for key, value in image.items()}
        case _:
            pytest.fail(f"{path.relative_to(_ROOT)} must configure the OpenTelemetry test image")


def test_opentelemetry_test_framework_image_has_one_versioned_digest_owner() -> None:
    application_image = _opentelemetry_test_framework_image(_CHART / "values.yaml")
    foundation_image = _opentelemetry_test_framework_image(_ROOT / "infra" / "k8s" / "helm-foundation" / "values.yaml")

    assert application_image == foundation_image, (
        "OpenTelemetry test image pins must match between application and foundation"
    )
    image = application_image
    assert image.get("repository") == "busybox"
    assert _image_pin_is_unambiguous(image), f"Helm busybox image must be <version>@sha256:<digest>: {image!r}"
    tag = image["tag"]
    assert isinstance(tag, str)
    reference = f"{image['repository']}:{tag}"
    assert reference.count("@sha256:") == 1, f"Helm busybox reference must contain exactly one digest: {reference}"


@pytest.mark.parametrize(
    "image",
    [
        {
            "tag": "v1.12.2@sha256:f94b1c82957accb77cd11385fd5e3600758ef1b1ab79557c97319ad28590735a",
            "digest": "sha256:f94b1c82957accb77cd11385fd5e3600758ef1b1ab79557c97319ad28590735a",
        },
        {
            "tag": "v0.81.0@sha256:959d47672fbff2776a04ec62b8afcec89e8c036af84dc5fade50019dab212746",
            "digest": "sha256:959d47672fbff2776a04ec62b8afcec89e8c036af84dc5fade50019dab212746",
        },
        {
            "tag": "sha256-" + "a" * 64 + "@sha256:" + "a" * 64,
        },
        {
            "tag": "1.37.0@sha256:" + "a" * 64 + "@sha256:" + "a" * 64,
        },
    ],
)
def test_observability_pin_guard_rejects_ambiguous_or_versionless_pins(image: dict[str, str]) -> None:
    assert not _image_pin_is_unambiguous(image)


def test_loki_and_cache_images_are_aligned_without_config_changes() -> None:
    values = load_mapping(_CHART / "values.yaml")
    match values:
        case {
            "loki": {
                "loki": {"image": {"tag": str(loki_tag)}, "auth_enabled": auth_enabled},
                "lokiCanary": {"image": {"tag": str(canary_tag)}},
                "chunksCache": {"image": {"tag": str(chunks_cache_tag)}},
                "resultsCache": {"image": {"tag": str(results_cache_tag)}},
                "memcached": {"image": {"tag": str(memcached_tag)}},
                "deploymentMode": deployment_mode,
            },
            "tempo-distributed": {
                "memcached": {"image": {"tag": str(tempo_cache_tag)}},
                "tempo": {"structuredConfig": {"multitenancy_enabled": tempo_multitenancy}},
            },
            "mimir-distributed": {"mimir": {"structuredConfig": {"multitenancy_enabled": mimir_multitenancy}}},
        }:
            pass
        case _:
            pytest.fail("observability values must contain the expected image and tenancy fields")
    cache_tags = {chunks_cache_tag, results_cache_tag, memcached_tag}

    assert loki_tag.split("@", 1)[0] == canary_tag.split("@", 1)[0]
    assert cache_tags == {"1.6.45-alpine@sha256:c29847751abb41f4c268c84fb3087fee05d4edcbda44409ccb5086e26148e8a7"}
    assert tempo_cache_tag == next(iter(cache_tags))
    assert deployment_mode == "SimpleScalable"
    assert auth_enabled is True
    assert mimir_multitenancy is True
    assert tempo_multitenancy is True


def test_compose_and_chart_runtime_images_are_exactly_aligned() -> None:
    compose = (_ROOT / "infra/compose/docker-compose.yml").read_text(encoding="utf-8")
    values = load_mapping(_CHART / "values.yaml")
    docling = load_mapping(_CHART / "charts/docling-serve/values.yaml")

    mimir = "3.1.2@sha256:39cc23910bbaa60d0280fd162265a22c39120ff61b02bc993f3fd3701fb8606d"
    prometheus_tag = "v3.13.1"
    prometheus_digest = "3c42b892cf723fa54d2f262c37a0e1f80aa8c8ddb1da7b9b0df9455a35a7f893"
    docling_tag = "v1.26.0@sha256:7e07522e0240c1db3ff5b837ffa969c2ecd5a71664c0e0369f5a69fc169e30ba"

    match values:
        case {
            "mimir-distributed": {"image": {"tag": rendered_mimir_tag}},
            "kube-prometheus-stack": {"prometheus": {"prometheusSpec": {"image": prometheus_image}}},
        }:
            pass
        case _:
            pytest.fail("chart values must contain the Mimir and Prometheus image settings")
    assert rendered_mimir_tag == mimir
    assert prometheus_image == {
        "repository": "prometheus/prometheus",
        "tag": prometheus_tag,
        "sha": prometheus_digest,
    }
    assert docling["image"] == {
        "repository": "quay.io/docling-project/docling-serve-cpu",
        "tag": docling_tag,
        "pullPolicy": "IfNotPresent",
    }
    assert f"docker.io/grafana/mimir:{mimir}" in compose
    assert f"quay.io/prometheus/prometheus:{prometheus_tag}@sha256:{prometheus_digest}" in compose
    assert f"quay.io/docling-project/docling-serve-cpu:{docling_tag}" in compose


def test_expected_residual_scan_findings_remain_explicitly_classified() -> None:
    assert _EXPECTED_SCAN_FINDINGS == {
        "loki": (1, 0),
        "loki-canary": (1, 0),
        "tempo": (4, 0),
        "mimir": (1, 0),
        "memcached": (0, 0),
        "memcached-exporter": (25, 1),
    }
    assert any(high or critical for high, critical in _EXPECTED_SCAN_FINDINGS.values())

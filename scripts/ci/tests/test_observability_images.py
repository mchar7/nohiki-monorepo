from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml
from _documents import Manifest, load_manifests, load_mapping, mapping_at
from helm_test_utils import runtime_eso_args
from test_image_digest_gitops import _digest_values

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION_TAG = re.compile(r"^v?[0-9][A-Za-z0-9_.-]{0,126}$")
_PINNED_TAG = re.compile(r"^v?[0-9][A-Za-z0-9_.-]{0,126}@sha256:[0-9a-f]{64}$")
_IMAGE_PATHS = {
    "alloy": ("values.yaml", ("pyroscope", "alloy", "image")),
    "config-reloader": ("values.yaml", ("pyroscope", "alloy", "configReloader", "image")),
    "loki": ("values.yaml", ("loki", "loki", "image")),
    "loki-canary": ("values.yaml", ("loki", "lokiCanary", "image")),
    "memcached": ("values.yaml", ("loki", "memcached", "image")),
    "memcached-exporter": ("values.yaml", ("loki", "memcachedExporter", "image")),
    "mimir": ("values.yaml", ("mimir-distributed", "image")),
    "nginx": ("values.yaml", ("loki", "gateway", "image")),
    "pyroscope": ("values.yaml", ("pyroscope", "pyroscope", "image")),
    "sidecar": ("values.yaml", ("loki", "sidecar", "image")),
    "tempo": ("charts/tempo-monolithic/values.yaml", ("image",)),
}
_UPGRADED_IMAGE_COUNTS = {
    "loki": 3,
    "loki-canary": 1,
    "mimir": 15,
    "tempo": 1,
    "memcached": 2,
    "memcached-exporter": 2,
}
_LOCAL_IMAGE_COUNTS = {
    "loki": 3,
    "loki-canary": 0,
    "mimir": 8,
    "tempo": 1,
    "memcached": 0,
    "memcached-exporter": 0,
}
_LOCAL_DISABLED_IMAGES = {"loki-canary", "memcached", "memcached-exporter"}
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


def _image_ref(image: Mapping[str, object]) -> str:
    assert _image_pin_is_unambiguous(image), image
    repository = image.get("repository")
    registry = image.get("registry")
    tag = image["tag"]
    digest = image.get("digest")
    assert isinstance(repository, str)
    assert isinstance(tag, str)
    if isinstance(registry, str) and registry and not repository.startswith(f"{registry}/"):
        repository = f"{registry}/{repository}"
    if isinstance(digest, str):
        return f"{repository}@{digest}"
    return f"{repository}:{tag}"


def _live_image_refs() -> dict[str, str]:
    documents: dict[str, Mapping[str, object]] = {}
    refs: dict[str, str] = {}
    for name, (values_file, path) in _IMAGE_PATHS.items():
        values = documents.setdefault(values_file, load_mapping(_CHART / values_file))
        image = mapping_at(values, *path)
        refs[name] = _image_ref(image)
    return refs


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
    refs = _live_image_refs()
    digests = {image.partition("@")[2] for image in refs.values()}
    affected = [image for image in rendered_images if image.partition("@")[2] in digests]
    expected_names = set(refs)
    count_ledger = _UPGRADED_IMAGE_COUNTS
    if values_file == "values.local.yaml":
        expected_names -= _LOCAL_DISABLED_IMAGES
        count_ledger = _LOCAL_IMAGE_COUNTS
    expected_images = {refs[name] for name in expected_names}
    expected_counts = {refs[name]: count for name, count in count_ledger.items()}
    expected_repositories = {re.sub(r":[^/]+$", "", image.partition("@")[0]) for image in expected_images}

    assert documents
    assert all("apiVersion" in document and "kind" in document for document in documents)
    assert set(affected) == expected_images
    assert not any(image.startswith(_FORBIDDEN_PREFIXES) for image in rendered_images)
    actual_counts = {image: rendered_images.count(image) for image in expected_counts}
    assert actual_counts == expected_counts

    by_repository: dict[str, set[str]] = {}
    for image in affected:
        repository, separator, digest = image.partition("@")
        assert separator, image
        assert _DIGEST.fullmatch(digest), image
        by_repository.setdefault(repository.partition(":")[0], set()).add(image)

    assert set(by_repository) == expected_repositories
    assert all(len(images) == 1 for images in by_repository.values())


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
            "tag": "v9.9.9@sha256:" + "a" * 64,
            "digest": "sha256:" + "b" * 64,
        },
        {
            "tag": "v8.8.8@sha256:" + "b" * 64,
            "digest": "sha256:" + "a" * 64,
        },
        {
            "tag": "sha256-" + "a" * 64 + "@sha256:" + "a" * 64,
        },
        {
            "tag": "7.7.7@sha256:" + "a" * 64 + "@sha256:" + "a" * 64,
        },
    ],
)
def test_observability_pin_guard_rejects_ambiguous_or_versionless_pins(image: dict[str, str]) -> None:
    assert not _image_pin_is_unambiguous(image)


def test_local_mimir_and_loki_disable_replica_amplification() -> None:
    values = load_mapping(_CHART / "values.local.yaml")
    mimir = mapping_at(values, "mimir-distributed")
    assert all(
        mapping_at(mimir, component).get("enabled") is False
        for component in ("alertmanager", "kafka", "overrides_exporter", "query_scheduler", "rollout_operator")
    )
    assert mapping_at(mimir, "mimir", "structuredConfig", "ingest_storage").get("enabled") is False
    for component in ("distributor", "ingester", "querier", "query_frontend", "store_gateway", "compactor", "ruler"):
        assert mapping_at(mimir, component).get("replicas") == 1
    assert mapping_at(mimir, "ingester", "zoneAwareReplication").get("enabled") is False
    assert mapping_at(mimir, "store_gateway", "zoneAwareReplication").get("enabled") is False

    loki = mapping_at(values, "loki")
    assert all(
        mapping_at(loki, component).get("enabled") is False
        for component in ("chunksCache", "lokiCanary", "resultsCache")
    )
    assert all(mapping_at(loki, component).get("replicas") == 1 for component in ("backend", "read", "write"))


def test_local_mimir_classic_ingestion_keeps_the_push_api_enabled(tmp_path: Path) -> None:
    documents = _render("values.local.yaml", tmp_path)
    configmap = next(
        document
        for document in documents
        if document["kind"] == "ConfigMap" and document["metadata"]["name"] == "nohiki-mimir-config"
    )
    config = yaml.safe_load(configmap["data"]["mimir.yaml"])
    assert config["ingest_storage"]["enabled"] is False
    assert config["ingester"]["push_grpc_method_enabled"] is True


def test_loki_and_cache_images_are_aligned_without_config_changes() -> None:
    values = load_mapping(_CHART / "values.yaml")
    tempo = load_mapping(_CHART / "charts" / "tempo-monolithic" / "values.yaml")
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
            "mimir-distributed": {"mimir": {"structuredConfig": {"multitenancy_enabled": mimir_multitenancy}}},
        }:
            pass
        case _:
            pytest.fail("observability values must contain the expected image and tenancy fields")
    match tempo:
        case {
            "image": {"tag": str(tempo_tag)},
            "config": {"multitenancy_enabled": tempo_multitenancy},
        }:
            pass
        case _:
            pytest.fail("Tempo values must contain the expected image and tenancy fields")
    cache_tags = {chunks_cache_tag, results_cache_tag, memcached_tag}

    assert loki_tag.split("@", 1)[0] == canary_tag.split("@", 1)[0]
    assert cache_tags == {memcached_tag}
    assert _PINNED_TAG.fullmatch(tempo_tag)
    assert deployment_mode == "SimpleScalable"
    assert auth_enabled is True
    assert mimir_multitenancy is True
    assert tempo_multitenancy is True


def test_compose_and_chart_shared_runtime_images_are_exactly_aligned() -> None:
    compose = load_mapping(_ROOT / "infra/compose/docker-compose.yml")
    services = mapping_at(compose, "services")
    values = load_mapping(_CHART / "values.yaml")
    docling = load_mapping(_CHART / "charts/docling-serve/values.yaml")
    refs = _live_image_refs()

    prometheus_image = mapping_at(
        values,
        "kube-prometheus-stack",
        "prometheus",
        "prometheusSpec",
        "image",
    )
    prometheus_repository = prometheus_image.get("repository")
    prometheus_tag = prometheus_image.get("tag")
    prometheus_sha = prometheus_image.get("sha")
    assert isinstance(prometheus_repository, str)
    assert isinstance(prometheus_tag, str)
    assert _VERSION_TAG.fullmatch(prometheus_tag)
    assert isinstance(prometheus_sha, str)
    assert re.fullmatch(r"[0-9a-f]{64}", prometheus_sha)
    prometheus_ref = f"quay.io/{prometheus_repository}:{prometheus_tag}@sha256:{prometheus_sha}"

    docling_image = mapping_at(docling, "image")
    assert _image_pin_is_unambiguous(docling_image)
    expected = {
        "nohiki-infra-docling": _image_ref(docling_image),
        "nohiki-obs-mimir": refs["mimir"],
        "nohiki-obs-prometheus": prometheus_ref,
    }
    actual = {name: mapping_at(services, name).get("image") for name in expected}
    assert actual == expected

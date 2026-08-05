"""Contracts for persistent local image delivery through native k3s."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from contextlib import nullcontext
from functools import cache
from pathlib import Path
from typing import TypeIs

import pytest
import yaml
from _documents import load_mapping, string_at
from helm_test_utils import runtime_eso_args


def _is_mapping(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> dict[str, object]:
    assert _is_mapping(value)
    return value


def _mapping_at(mapping: Mapping[str, object], key: str) -> dict[str, object]:
    return _mapping(mapping[key])


def _mapping_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_mapping(item) for item in value]


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _strings(value: object) -> list[str]:
    assert isinstance(value, list)
    return [_string(item) for item in value]


def _images(value: object) -> list[str]:
    if isinstance(value, dict):
        images = [image] if isinstance(image := value.get("image"), str) else []
        return images + [image for child in value.values() for image in _images(child)]
    if isinstance(value, list):
        return [image for child in value for image in _images(child)]
    return []


_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "infra" / "k8s" / "local" / "image_foundation.py"
_IMAGE_FOUNDATION_SPEC = importlib.util.spec_from_file_location("image_foundation_under_test", _SCRIPT)
assert _IMAGE_FOUNDATION_SPEC is not None
assert _IMAGE_FOUNDATION_SPEC.loader is not None
_IMAGE_FOUNDATION = importlib.util.module_from_spec(_IMAGE_FOUNDATION_SPEC)
_IMAGE_FOUNDATION_SPEC.loader.exec_module(_IMAGE_FOUNDATION)


_INVENTORY = _ROOT / "infra" / "k8s" / "local" / "images.json"
_REGISTRY = _ROOT / "infra" / "k8s" / "gitops" / "registry"
_JUSTFILE = _ROOT / "Justfile"
_LIFECYCLE = _ROOT / "infra" / "k8s" / "local" / "lifecycle.sh"
_LOCAL_PLATFORM = _ROOT / "infra" / "k8s" / "gitops" / "platform" / "local"
_DIGEST_VALUES = _LOCAL_PLATFORM / "image-digests.values.yaml"
_REGISTRY_NAME = "localhost:5000"
_ENDPOINT = "http://127.0.0.1:30500"
_DIGEST = "sha256:" + "a" * 64
_EXPECTED_IMAGES = {
    "frontend",
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
    "ml-compute-service-gpu",
    "sys-tick-job",
    "snapshot-refresh-job",
    "qdrant-init",
    "kafka-connect",
    "api-verification-runner",
    "playwright-verification-runner",
    "health-runner",
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    assert _SCRIPT.is_file(), f"missing image foundation CLI: {_SCRIPT}"
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@cache
def _inventory() -> dict[str, object]:
    return load_mapping(_INVENTORY)


@cache
def _local_names() -> tuple[str, ...]:
    document = _inventory()
    images = document["images"]
    assert isinstance(images, list)
    return tuple(string_at(entry, "name") for entry in _mapping_list(images) if entry["local"])


def _write_digests(path: Path, *, tag: str | None = None) -> Path:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "registry": _REGISTRY_NAME,
                "images": {name: {"tag": tag or f"sha256-{'a' * 64}", "digest": _DIGEST} for name in _local_names()},
            }
        ),
        encoding="utf-8",
    )
    return path


def _publish_with_image_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    image_id: str,
    *,
    runtime: str,
) -> tuple[list[list[str]], Path]:
    """Invoke the public publish command with one controlled runtime result."""
    commands: list[list[str]] = []
    image = {
        "name": "user-auth-service",
        "context": "backend/services/user-auth-service",
        "dockerfile": "Dockerfile",
        "local": True,
    }

    def fake_run(argv: list[str], *, capture: bool = False) -> str:
        if capture:
            return image_id
        commands.append(argv)
        return ""

    def fake_http_request(*_args: object, **_kwargs: object) -> tuple[int, dict[str, str]]:
        return 200, {"Docker-Content-Digest": _DIGEST}

    monkeypatch.setattr(_IMAGE_FOUNDATION, "local_images", lambda: [image])
    monkeypatch.setattr(_IMAGE_FOUNDATION, "registry_forward", nullcontext)
    monkeypatch.setattr(_IMAGE_FOUNDATION, "run", fake_run)
    monkeypatch.setattr(
        _IMAGE_FOUNDATION,
        "_http_request",
        fake_http_request,
    )

    output = tmp_path / "digests.json"
    _IMAGE_FOUNDATION.cmd_publish(argparse.Namespace(runtime=runtime, digests=str(output)))
    return commands, output


@pytest.mark.parametrize(
    ("runtime", "image_id"),
    [("podman", "a" * 64), ("docker", "sha256:" + "b" * 64)],
)
def test_publish_accepts_runtime_image_ids_and_builds_canonical_tag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime: str,
    image_id: str,
) -> None:
    commands, output = _publish_with_image_id(monkeypatch, tmp_path, image_id, runtime=runtime)
    content_id = image_id.removeprefix("sha256:")
    target = f"{_REGISTRY_NAME}/user-auth-service:sha256-{content_id}"
    push = [
        runtime,
        "push",
        *(["--tls-verify=false"] if runtime == "podman" else []),
        target,
    ]

    assert commands == [
        [runtime, "tag", "nohiki-build/user-auth-service:local", target],
        push,
    ]
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["images"]["user-auth-service"] == {
        "tag": f"sha256-{content_id}",
        "digest": _DIGEST,
    }


@pytest.mark.parametrize(
    "image_id",
    [
        "A" * 64,
        "",
        "a" * 63,
        "a" * 65,
        "sha256:" + "A" * 64,
        "sha512:" + "a" * 64,
        "sha256-" + "a" * 64,
        "sha256:" + "a" * 63 + "g",
    ],
    ids=[
        "uppercase",
        "zero-length",
        "short",
        "long",
        "uppercase-prefixed",
        "other-algorithm",
        "malformed",
        "malformed-hex",
    ],
)
def test_publish_rejects_noncanonical_runtime_image_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    image_id: str,
) -> None:
    output = tmp_path / "digests.json"
    with pytest.raises(SystemExit, match=r"local image .* has no content digest"):
        _publish_with_image_id(monkeypatch, tmp_path, image_id, runtime="podman")
    assert not output.exists()


def test_registry_forward_sets_reuseaddr_before_refusing_active_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []

    class OccupiedProbe:
        def setsockopt(self, *args: object) -> None:
            events.append(("setsockopt", *args))

        def bind(self, address: object) -> None:
            events.append(("bind", address))
            raise OSError from None

        def close(self) -> None:
            events.append(("close",))

    monkeypatch.setattr(_IMAGE_FOUNDATION.socket, "socket", OccupiedProbe)
    with (
        pytest.raises(SystemExit, match="localhost:5000 is already in use"),
        _IMAGE_FOUNDATION.registry_forward(),
    ):
        pytest.fail("registry forwarding must refuse an occupied port")

    assert events == [
        (
            "setsockopt",
            _IMAGE_FOUNDATION.socket.SOL_SOCKET,
            _IMAGE_FOUNDATION.socket.SO_REUSEADDR,
            1,
        ),
        ("bind", ("127.0.0.1", 5000)),
        ("close",),
    ]


def _write_nodes(path: Path, names_by_node: list[list[str]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "metadata": {"name": f"node-{index}"},
                        "status": {"images": [{"names": [name]} for name in node_images]},
                    }
                    for index, node_images in enumerate(names_by_node)
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _recipe(justfile: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}(?:\s[^:\n]*)?:[^\n]*\n(?P<body>(?:^[ \t].*\n|^\s*$)*)",
        justfile,
    )
    assert match, f"missing Just recipe {name!r}"
    return match.group(0)


def _shell_function(script: str, name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n(?P<body>.*?)^\}}", script)
    assert match, f"missing shell function {name!r}"
    return match.group(0)


@cache
def _load_yaml(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return _mapping(document)


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_registry_is_in_cluster_and_persistent() -> None:
    kustomization = _load_yaml(_REGISTRY / "kustomization.yaml")
    assert set(_strings(kustomization["resources"])) == {
        "namespace.yaml",
        "pvc.yaml",
        "deployment.yaml",
        "service.yaml",
    }
    deployment = _load_yaml(_REGISTRY / "deployment.yaml")
    claim = _load_yaml(_REGISTRY / "pvc.yaml")
    service = _load_yaml(_REGISTRY / "service.yaml")
    pod = _mapping_at(_mapping_at(_mapping_at(deployment, "spec"), "template"), "spec")
    claim_name = _mapping_at(claim, "metadata")["name"]
    assert any(
        _mapping_at(volume, "persistentVolumeClaim").get("claimName") == claim_name
        for volume in _mapping_list(pod["volumes"])
    )
    assert any(
        mount["mountPath"] == "/var/lib/registry"
        for container in _mapping_list(pod["containers"])
        for mount in _mapping_list(container["volumeMounts"])
    )
    service_spec = _mapping_at(service, "spec")
    assert service_spec["type"] == "NodePort"
    ports = _mapping_list(service_spec["ports"])
    assert len(ports) == 1
    assert (ports[0]["port"], ports[0]["targetPort"], ports[0]["nodePort"]) == (
        5000,
        "registry",
        30500,
    )


def test_inventory_is_complete_authoritative_and_includes_frontend() -> None:
    result = _run("validate")
    assert result.returncode == 0, result.stderr
    document = _inventory()
    assert document["schemaVersion"] == 1
    images = _mapping_list(document["images"])
    names = [string_at(entry, "name") for entry in images]
    assert len(names) == len(set(names))
    assert set(names) == _EXPECTED_IMAGES
    frontend = next(entry for entry in images if entry["name"] == "frontend")
    assert frontend == {
        "name": "frontend",
        "context": ".",
        "dockerfile": "typescript/apps/frontend/Dockerfile",
        "local": True,
    }


def test_native_k3s_mirror_round_trip_is_exact(tmp_path: Path) -> None:
    rendered = _run("mirror-config", "--endpoint", _ENDPOINT)
    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert config == {"mirrors": {_REGISTRY_NAME: {"endpoint": [_ENDPOINT]}}}
    path = tmp_path / "registries.yaml"
    path.write_text(rendered.stdout, encoding="utf-8")
    checked = _run("mirror-preflight", "--config", str(path), "--endpoint", _ENDPOINT)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize(
    ("content", "endpoint"),
    [
        (None, _ENDPOINT),
        ("not: [valid", _ENDPOINT),
        (
            yaml.safe_dump({"mirrors": {_REGISTRY_NAME: {"endpoint": ["http://127.0.0.1:30501"]}}}),
            _ENDPOINT,
        ),
        (
            yaml.safe_dump(
                {
                    "mirrors": {
                        _REGISTRY_NAME: {"endpoint": [_ENDPOINT]},
                        "extra": {"endpoint": [_ENDPOINT]},
                    }
                }
            ),
            _ENDPOINT,
        ),
        (
            yaml.safe_dump({"mirrors": {_REGISTRY_NAME: {"endpoint": [_ENDPOINT]}}}),
            "https://127.0.0.1:30500",
        ),
    ],
    ids=("absent", "malformed", "wrong-port", "extra-mirror", "scheme-drift"),
)
def test_native_k3s_mirror_preflight_fails_closed(tmp_path: Path, content: str | None, endpoint: str) -> None:
    path = tmp_path / "registries.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(SystemExit, match="mirror"):
        _IMAGE_FOUNDATION.cmd_mirror_preflight(argparse.Namespace(config=str(path), endpoint=endpoint))


@pytest.mark.parametrize("tag", ["latest", "dev"])
def test_digest_values_reject_mutable_tag_drift(tmp_path: Path, tag: str) -> None:
    digests = _write_digests(tmp_path / "digests.json", tag=tag)
    with pytest.raises(SystemExit, match="content-addressed"):
        _IMAGE_FOUNDATION.cmd_render_values(argparse.Namespace(digests=str(digests)))


def test_rendered_values_are_digest_only_and_cover_local_inventory(
    tmp_path: Path,
) -> None:
    result = _run("render-values", "--digests", str(_write_digests(tmp_path / "digests.json")))
    assert result.returncode == 0, result.stderr
    values = _mapping(yaml.safe_load(result.stdout))
    digest_map = _mapping_at(_mapping_at(values, "global"), "imageDigests")
    assert set(digest_map) == {f"{_REGISTRY_NAME}/{name}" for name in _local_names()}
    assert set(_strings(list(digest_map.values()))) == {_DIGEST}
    foundation = _mapping_at(values, "imageFoundation")
    assert foundation["schemaVersion"] == 1
    assert foundation["registry"] == _REGISTRY_NAME
    assert set(_mapping(foundation["images"])) == set(_local_names())
    assert "latest" not in result.stdout
    assert ":dev" not in result.stdout


def test_rendered_values_feed_local_helm_release_as_digest_references(tmp_path: Path) -> None:
    result = _run("render-values", "--digests", str(_write_digests(tmp_path / "digests.json")))
    assert result.returncode == 0, result.stderr
    digest_values = tmp_path / "image-digests.values.yaml"
    digest_values.write_text(result.stdout, encoding="utf-8")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_ROOT / "infra/k8s/helm"),
        "--namespace",
        "nohiki",
        "--values",
        str(_ROOT / "infra/k8s/helm/values.yaml"),
        "--values",
        str(_ROOT / "infra/k8s/helm/values.local.yaml"),
        "--values",
        str(digest_values),
        *runtime_eso_args("local"),
    ]
    rendered = subprocess.run(command, cwd=_ROOT, capture_output=True, text=True, check=False)
    assert rendered.returncode == 0, rendered.stderr
    local_images = [
        image
        for document in yaml.safe_load_all(rendered.stdout)
        for image in _images(document)
        if image.startswith(f"{_REGISTRY_NAME}/")
    ]
    assert local_images
    invalid = [
        image
        for image in local_images
        if re.fullmatch(
            rf"{re.escape(_REGISTRY_NAME)}/[^:@]+(?::[^@]+)?@sha256:[0-9a-f]{{64}}",
            image,
        )
        is None
    ]
    assert not invalid, sorted(set(invalid))


def test_every_node_proves_every_canonical_digest_pull(tmp_path: Path) -> None:
    digests = _write_digests(tmp_path / "digests.json")
    canonical = [f"{_REGISTRY_NAME}/{name}@{_DIGEST}" for name in _local_names()]
    nodes = _write_nodes(tmp_path / "nodes.json", [canonical, canonical])
    _IMAGE_FOUNDATION.cmd_verify_pulls(argparse.Namespace(digests=str(digests), nodes_json=str(nodes)))


@pytest.mark.parametrize("evidence", ["missing-on-node", "tag-only", "unqualified-digest"])
def test_pull_proof_rejects_cache_only_or_incomplete_evidence(tmp_path: Path, evidence: str) -> None:
    digests = _write_digests(tmp_path / "digests.json")
    canonical = [f"{_REGISTRY_NAME}/{name}@{_DIGEST}" for name in _local_names()]
    if evidence == "missing-on-node":
        node_images = [canonical, canonical[:-1]]
    elif evidence == "tag-only":
        node_images = [
            canonical,
            [f"{_REGISTRY_NAME}/{name}:sha256-{'a' * 64}" for name in _local_names()],
        ]
    else:
        node_images = [canonical, [f"{name}@{_DIGEST}" for name in _local_names()]]
    nodes = _write_nodes(tmp_path / "nodes.json", node_images)
    with pytest.raises(SystemExit, match="node"):
        _IMAGE_FOUNDATION.cmd_verify_pulls(argparse.Namespace(digests=str(digests), nodes_json=str(nodes)))


def test_publish_is_separate_and_normal_reconcile_has_no_host_registry_lifecycle() -> None:
    justfile = _text(_JUSTFILE)
    publish_recipe = _recipe(justfile, "k8s-publish-local-images")
    reconcile_recipe = _recipe(justfile, "k8s-reconcile-local")
    assert "infra/k8s/local/lifecycle.sh publish" in publish_recipe
    assert "infra/k8s/local/lifecycle.sh reconcile" in reconcile_recipe
    lifecycle = _text(_LIFECYCLE)
    publish = _shell_function(lifecycle, "publish")
    reconcile = _shell_function(lifecycle, "reconcile")
    assert '"$image_helper" build' in publish
    assert '"$image_helper" publish' in publish
    assert '"$image_helper"' not in reconcile
    for retired in ("k8s-registry-up", "k8s-build", "k8s-push-images"):
        assert not re.search(rf"(?m)^{re.escape(retired)}(?:\s|:)", justfile)
    assert "docker run" not in reconcile
    assert "podman run" not in reconcile


def test_local_helmrelease_consumes_stable_committed_digest_values() -> None:
    kustomization = _load_yaml(_LOCAL_PLATFORM / "kustomization.yaml")
    assert kustomization["configMapGenerator"] == [
        {
            "name": "nohiki-image-digests",
            "namespace": "flux-system",
            "files": ["values.yaml=image-digests.values.yaml"],
        }
    ]
    generator_options = _mapping_at(kustomization, "generatorOptions")
    assert generator_options["disableNameSuffixHash"] is True
    patches = _mapping_list(kustomization["patches"])
    patch = yaml.safe_load(str(patches[0]["patch"]))
    assert patch[0] == {
        "op": "add",
        "path": "/spec/valuesFrom",
        "value": [
            {
                "kind": "ConfigMap",
                "name": "nohiki-image-digests",
                "valuesKey": "values.yaml",
                "optional": False,
            },
            {
                "kind": "ConfigMap",
                "name": "nohiki-owner-model-egress-values",
                "valuesKey": "values.yaml",
                "optional": False,
            },
        ],
    }
    runtime_secrets = _load_yaml(_ROOT / "infra/k8s/gitops/clusters/local/runtime-secrets.yaml")
    runtime_spec = _mapping_at(runtime_secrets, "spec")
    assert _mapping_list(runtime_spec["healthChecks"])[:2] == [
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "name": "nohiki-llm-proxy-source",
            "namespace": "nohiki",
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "name": "nohiki-owner-model-egress-values",
            "namespace": "flux-system",
        },
    ]
    values = _load_yaml(_DIGEST_VALUES)
    global_values = _mapping_at(values, "global")
    digest_map = _mapping_at(global_values, "imageDigests")
    if digest_map:
        assert global_values["imageTag"] == "immutable"
        assert set(digest_map) == {f"{_REGISTRY_NAME}/{name}" for name in _local_names()}
        assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", _string(digest)) for digest in digest_map.values())
        foundation = _mapping_at(values, "imageFoundation")
        assert foundation["schemaVersion"] == 1
        assert foundation["registry"] == _REGISTRY_NAME
        assert set(_mapping(foundation["images"])) == set(_local_names())
    else:
        assert global_values["imageTag"] == "publish-required"
        assert "imageFoundation" not in values


def test_publish_git_write_is_guarded_to_reviewed_digest_artifact() -> None:
    lifecycle = _text(_LIFECYCLE)
    publish = _shell_function(lifecycle, "publish")
    artifact = "infra/k8s/gitops/platform/local/image-digests.values.yaml"
    assert f'local artifact="{artifact}"' in publish
    assert "NOHIKI_RUNTIME_CONTROL_BRANCH" in publish
    assert "NOHIKI_REVIEWED_TOPIC_SHA" in publish
    assert "^[0-9a-f]{40}$" in publish
    assert '[[ "$head" == "$reviewed" ]]' in publish
    assert '[[ "$remote" == "$reviewed" ]]' in publish
    assert '[[ "$path" == "$artifact" ]]' in publish
    assert 'git add -- "$artifact"' in publish
    assert 'git commit -m "chore(kind): publish local image digests" -- "$artifact"' in publish
    assert "git diff --cached --name-only" in publish
    assert 'git diff-tree --no-commit-id --name-only -r "$after"' in publish
    assert re.search(r"\bgit\s+push\b", publish) is None
    assert "Prepared digest artifact commit for PUSH-DELEGATE" in publish
    assert "image references are redacted" in publish
    assert "before=%s after=%s path=%s" in publish
    assert 'cat "$artifact"' not in publish

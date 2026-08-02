#!/usr/bin/env python3
"""Reproduce and verify the private Flux runtime artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "infra/k8s/flux-runtime"
LOCK = RUNTIME / "artifacts.lock.yaml"
CHART = RUNTIME / "vendor/flux-operator-0.55.0.tgz"
CHART_MANIFEST = RUNTIME / "vendor/flux-operator-0.55.0.oci-manifest.json"
OPERATOR_INDEX = RUNTIME / "vendor/flux-operator-v0.55.0.oci-index.json"
VALUES = RUNTIME / "operator-values.yaml"
OPERATOR_INSTALL = RUNTIME / "operator-install.yaml"
FALLBACK_INSTALL = RUNTIME / "fallback/install.yaml"
REGISTRY = ROOT / "infra/k8s/gitops/registry/deployment.yaml"
GENERATOR = Path(__file__).resolve()
HELM_VERSION = "v4.2.2"
DIGEST_PREFIX = "sha256:"
DIGEST_LENGTH = len(DIGEST_PREFIX) + 64


class _ArtifactError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(value: object, message: str) -> None:
    if not value:
        raise _ArtifactError(message)


def _mapping(value: object, name: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{name} must be an object")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))


def _image_strings(path: Path) -> set[str]:
    images: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "image" and isinstance(item, str):
                    images.add(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        visit(document)
    return images


def _operator_identity() -> tuple[str, str, str]:
    overrides = _load_yaml(VALUES)
    override_image = _mapping(overrides.get("image"), "operator values image")
    with tarfile.open(CHART, mode="r:gz") as archive:
        defaults_file = archive.extractfile("flux-operator/values.yaml")
        _require(defaults_file is not None, "chart defaults are missing")
        defaults = _mapping(yaml.safe_load(defaults_file.read()), "chart defaults")
    default_image = _mapping(defaults.get("image"), "chart default image")
    repository = override_image.get("repository", default_image.get("repository"))
    tag = override_image.get("tag") or default_image.get("tag")
    _require(isinstance(repository, str) and repository, "operator repository is missing")
    _require(isinstance(tag, str) and tag, "operator tag is missing")
    index_digest = DIGEST_PREFIX + _sha256(OPERATOR_INDEX)
    index = json.loads(OPERATOR_INDEX.read_text(encoding="utf-8"))
    manifests = index.get("manifests")
    _require(isinstance(manifests, list), "operator OCI index manifests are missing")
    amd64 = [
        entry
        for entry in manifests
        if isinstance(entry, dict) and entry.get("platform") == {"architecture": "amd64", "os": "linux"}
    ]
    _require(len(amd64) == 1, "operator OCI index must contain one linux/amd64 manifest")
    platform_digest = amd64[0].get("digest")
    _require(isinstance(platform_digest, str), "operator linux/amd64 digest is missing")
    return f"{repository}:{tag}", f"{repository}@{index_digest}", platform_digest


def _render_operator() -> bytes:
    helm = shutil.which("helm")
    _require(helm is not None, "helm is missing")
    version = subprocess.run(  # noqa: S603
        (helm, "version", "--template", "{{.Version}}"),
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    _require(version == HELM_VERSION, f"helm version must be {HELM_VERSION}, got {version}")
    command = (
        helm,
        "template",
        "flux-operator",
        str(CHART.relative_to(ROOT)),
        "--namespace",
        "flux-system",
        "--values",
        str(VALUES.relative_to(ROOT)),
    )
    rendered = subprocess.run(  # noqa: S603
        command,
        check=True,
        cwd=ROOT,
        capture_output=True,
        timeout=60,
    ).stdout
    mutable, immutable, _ = _operator_identity()
    old = f'image: "{mutable}"'.encode()
    new = f'image: "{immutable}"'.encode()
    _require(rendered.count(old) == 1, "Helm output must contain exactly one mutable operator image")
    pinned = rendered.replace(old, new)
    _require(old not in pinned, "operator digest pin left a mutable image")
    _require(pinned.count(new) == 1, "operator digest pin was not applied exactly once")
    return pinned


def _verify_chart(lock: dict[str, Any]) -> None:
    chart = _mapping(lock.get("chart"), "chart")
    manifest_path = ROOT / str(chart.get("ociManifestPath", ""))
    _require(manifest_path == CHART_MANIFEST, "chart OCI manifest path is wrong")
    raw_chart = CHART_MANIFEST.read_bytes()
    expected_manifest_digest = DIGEST_PREFIX + hashlib.sha256(raw_chart).hexdigest()
    _require(
        chart.get("ociManifestDigest") == expected_manifest_digest,
        "chart OCI manifest digest is not derived from vendored upstream bytes",
    )
    manifest = json.loads(raw_chart)
    layers = manifest.get("layers")
    _require(
        isinstance(layers, list) and len(layers) == 1 and isinstance(layers[0], dict),
        "chart OCI manifest must contain one layer",
    )
    layer = layers[0]
    _require(
        layer.get("mediaType") == "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
        "chart OCI layer media type is wrong",
    )
    _require(
        layer.get("digest") == DIGEST_PREFIX + _sha256(CHART),
        "vendored chart does not match its upstream OCI layer",
    )
    _require(
        layer.get("size") == CHART.stat().st_size,
        "vendored chart size does not match its upstream OCI layer",
    )
    _require(chart.get("tgzSha256") == _sha256(CHART), "chart lock hash is wrong")


def _verify_operator(lock: dict[str, Any]) -> str:
    generated = _mapping(lock.get("generated"), "generated")
    operator = _mapping(generated.get("operatorInstall"), "generated.operatorInstall")
    generator = _mapping(operator.get("generator"), "generated.operatorInstall.generator")
    _require(
        generator.get("script") == str(GENERATOR.relative_to(ROOT)),
        "operator generator path is wrong",
    )
    _require(generator.get("scriptSha256") == _sha256(GENERATOR), "operator generator hash is wrong")
    _require(generator.get("binary") == "helm", "operator generator binary is wrong")
    _require(generator.get("version") == HELM_VERSION, "operator generator version is wrong")
    _require(
        operator.get("canonicalSha256") == _sha256(OPERATOR_INSTALL),
        "operator install hash is wrong",
    )
    _require(
        _render_operator() == OPERATOR_INSTALL.read_bytes(),
        "operator generator does not reproduce the committed digest-pinned manifest",
    )
    mutable, immutable, platform_digest = _operator_identity()
    _require(mutable not in _image_strings(OPERATOR_INSTALL), "operator install contains a mutable tag")
    _require(
        _image_strings(OPERATOR_INSTALL) == {immutable},
        "operator install image is not the independently derived OCI digest",
    )
    images = _mapping(lock.get("images"), "images")
    operator_image = _mapping(images.get("operator"), "images.operator")
    index_digest = DIGEST_PREFIX + _sha256(OPERATOR_INDEX)
    _require(operator_image.get("reference") == immutable, "operator reference does not match OCI evidence")
    _require(operator_image.get("indexOrImageDigest") == index_digest, "operator index digest is wrong")
    _require(
        operator_image.get("platformManifestDigest") == platform_digest,
        "operator platform digest is wrong",
    )
    return index_digest


def _verify_images(lock: dict[str, Any]) -> None:
    images = _mapping(lock.get("images"), "images")
    expected_names = {
        "operator",
        "sourceController",
        "kustomizeController",
        "helmController",
        "notificationController",
        "registry",
    }
    _require(set(images) == expected_names, "artifact image set is wrong")
    controller_names = (
        "sourceController",
        "kustomizeController",
        "helmController",
        "notificationController",
    )
    expected_fallback = {_mapping(images[name], f"images.{name}").get("reference") for name in controller_names}
    _require(_image_strings(FALLBACK_INSTALL) == expected_fallback, "fallback images do not match lock")
    registry_image = _mapping(images.get("registry"), "images.registry").get("reference")
    _require(_image_strings(REGISTRY) == {registry_image}, "registry image does not match lock")
    for name, raw in images.items():
        entry = _mapping(raw, f"images.{name}")
        reference = entry.get("reference")
        index = entry.get("indexOrImageDigest")
        _require(
            isinstance(reference, str) and isinstance(index, str) and reference.endswith("@" + index),
            f"images.{name} reference is not bound to its index digest",
        )
        for field in ("indexOrImageDigest", "platformManifestDigest", "runtimeImageId"):
            value = entry.get(field)
            _require(
                isinstance(value, str) and len(value) == DIGEST_LENGTH and value.startswith(DIGEST_PREFIX),
                f"images.{name}.{field} is not a digest",
            )


def _verify_paths(lock: dict[str, Any]) -> None:
    for section in ("generated", "manifests", "policies"):
        for name, raw in _mapping(lock.get(section), section).items():
            entry = _mapping(raw, f"{section}.{name}")
            path = ROOT / str(entry.get("path", ""))
            _require(path.is_file(), f"{section}.{name} path is missing")
            _require(entry.get("canonicalSha256") == _sha256(path), f"{section}.{name} hash is wrong")


def _verify() -> dict[str, str]:
    lock = _load_yaml(LOCK)
    expected_keys = {
        "apiVersion",
        "kind",
        "chart",
        "generated",
        "manifests",
        "policies",
        "images",
        "distribution",
    }
    _require(set(lock) == expected_keys, "artifact lock keys are not closed")
    _require(lock.get("apiVersion") == "nohiki.io/v1alpha1", "artifact lock apiVersion is wrong")
    _require(lock.get("kind") == "FluxRuntimeArtifactLock", "artifact lock kind is wrong")
    _verify_chart(lock)
    index_digest = _verify_operator(lock)
    _verify_images(lock)
    _verify_paths(lock)
    distribution = _mapping(lock.get("distribution"), "distribution")
    _require(
        distribution.get("operatorImageDigest") == index_digest,
        "distribution operator digest does not match OCI evidence",
    )
    _require(
        distribution.get("bootstrapFluxInstanceSha256") == _sha256(RUNTIME / "flux-instance-bootstrap.yaml"),
        "bootstrap FluxInstance hash is wrong",
    )
    _require(
        distribution.get("finalFluxInstanceSha256") == _sha256(RUNTIME / "flux-instance.yaml"),
        "final FluxInstance hash is wrong",
    )
    return {
        "artifactLockSha256": _sha256(LOCK),
        "chartLayerSha256": _sha256(CHART),
        "operatorImageDigest": index_digest,
        "operatorInstallSha256": _sha256(OPERATOR_INSTALL),
    }


def _write_output(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    """Run the requested artifact operation."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate-operator")
    generate.add_argument("--output", type=Path, required=True)
    subparsers.add_parser("verify")
    args = parser.parse_args()
    try:
        if args.command == "generate-operator":
            _write_output(args.output, _render_operator())
        else:
            sys.stdout.write(json.dumps(_verify(), sort_keys=True, separators=(",", ":")) + "\n")
    except (_ArtifactError, OSError, subprocess.SubprocessError, json.JSONDecodeError, yaml.YAMLError) as error:
        sys.stderr.write(f"flux runtime artifact verification failed: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[4]
_RUNTIME = _ROOT / "infra/k8s/flux-runtime"
_CLUSTER = _ROOT / "infra/k8s/gitops/clusters/local"
_RUNNER = _ROOT / "infra/k8s/local/kindctl"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_NAMES = {
    "operator",
    "sourceController",
    "kustomizeController",
    "helmController",
    "notificationController",
    "registry",
}


def _load(path: Path) -> dict[str, object]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    assert all(isinstance(key, str) for key in value)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _list(value: object) -> list[object]:
    assert isinstance(value, list)
    return list(value)


def _string(value: object) -> str:
    assert isinstance(value, str)
    return value


def _strings(value: object) -> list[str]:
    return [_string(item) for item in _list(value)]


def _at(document: dict[str, object], *path: str) -> object:
    value: object = document
    for key in path:
        value = _mapping(value)[key]
    return value


def _mapping_at(document: dict[str, object], *path: str) -> dict[str, object]:
    return _mapping(_at(document, *path))


def _string_at(document: dict[str, object], *path: str) -> str:
    return _string(_at(document, *path))


def _with_value(document: dict[str, object], path: tuple[str, ...], value: object) -> dict[str, object]:
    assert path
    updated = dict(document)
    key, *remaining = path
    if remaining:
        updated[key] = _with_value(_mapping(document[key]), tuple(remaining), value)
    else:
        updated[key] = value
    return updated


def _documents(path: Path) -> list[dict[str, object]]:
    loaded = yaml.safe_load_all(path.read_text(encoding="utf-8"))
    return [_mapping(document) for document in loaded]


def _load_runner() -> ModuleType:
    name = f"flux_runtime_kindctl_{id(object())}"
    loader = importlib.machinery.SourceFileLoader(name, str(_RUNNER))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_artifact_lock_is_closed_complete_and_binds_every_committed_byte() -> None:
    lock = _load(_RUNTIME / "artifacts.lock.yaml")
    assert set(lock) == {
        "apiVersion",
        "kind",
        "chart",
        "generated",
        "policies",
        "uninstallInventory",
        "images",
        "distribution",
    }
    assert lock["apiVersion"] == "nohiki.io/v1alpha1"
    assert lock["kind"] == "FluxRuntimeArtifactLock"

    chart = _mapping_at(lock, "chart")
    assert set(chart) == {"version", "source", "ociManifestDigest", "tgzPath", "tgzSha256"}
    assert chart["version"] == "0.55.0"
    chart_digest = _string(chart["ociManifestDigest"])
    chart_sha = _string(chart["tgzSha256"])
    assert _DIGEST.fullmatch(chart_digest)
    assert _HEX.fullmatch(chart_sha)
    assert chart_digest.removeprefix("sha256:") != chart_sha
    chart_path = _ROOT / _string(chart["tgzPath"])
    assert hashlib.sha256(chart_path.read_bytes()).hexdigest() == chart_sha

    generated = _mapping_at(lock, "generated")
    assert set(generated) == {"operatorInstall", "fallbackInstall"}
    for raw_entry in generated.values():
        entry = _mapping(raw_entry)
        assert set(entry) == {"path", "canonicalSha256", "generator"}
        canonical_sha = _string(entry["canonicalSha256"])
        assert _HEX.fullmatch(canonical_sha)
        artifact = _ROOT / _string(entry["path"])
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == canonical_sha
        generator = _mapping(entry["generator"])
        assert set(generator) == {"binary", "version", "argv", "inputSha256s"}
        assert _string(generator["binary"])
        assert _string(generator["version"])
        assert _list(generator["argv"])
        input_hashes = _mapping(generator["inputSha256s"])
        assert all(_HEX.fullmatch(_string(value)) for value in input_hashes.values())

    policy = _mapping_at(lock, "policies", "offlineEgress")
    assert set(policy) == {"path", "canonicalSha256"}
    policy_path = _string(policy["path"])
    assert policy_path == "infra/k8s/flux-runtime/offline-egress.nft"
    assert hashlib.sha256((_ROOT / policy_path).read_bytes()).hexdigest() == policy["canonicalSha256"]

    inventory = _mapping_at(lock, "uninstallInventory")
    assert set(inventory) == {
        "crds",
        "deployments",
        "clusterRoles",
        "clusterRoleBindings",
        "serviceAccounts",
    }
    assert all(values == sorted(values) for values in map(_strings, inventory.values()))

    images = _mapping_at(lock, "images")
    assert set(images) == _IMAGE_NAMES
    for raw_image in images.values():
        image = _mapping(raw_image)
        assert set(image) == {
            "reference",
            "indexOrImageDigest",
            "platform",
            "platformManifestDigest",
            "runtimeImageId",
        }
        assert image["platform"] == "linux/amd64"
        image_digest = _string(image["indexOrImageDigest"])
        platform_digest = _string(image["platformManifestDigest"])
        runtime_image_id = _string(image["runtimeImageId"])
        assert _DIGEST.fullmatch(image_digest)
        assert _DIGEST.fullmatch(platform_digest)
        assert _DIGEST.fullmatch(runtime_image_id)
        assert "@sha256:" in _string(image["reference"])
        assert image_digest != platform_digest
        assert platform_digest != runtime_image_id

    distribution = _mapping_at(lock, "distribution")
    assert set(distribution) == {
        "version",
        "kind",
        "operatorImageDigest",
        "canonicalRenderedResourcesSha256",
        "finalFluxInstanceSha256",
    }
    assert distribution["version"] == "2.9.2"
    assert distribution["kind"] == "embedded"
    assert _DIGEST.fullmatch(_string(distribution["operatorImageDigest"]))
    assert _HEX.fullmatch(_string(distribution["canonicalRenderedResourcesSha256"]))
    assert (
        hashlib.sha256((_RUNTIME / "flux-instance.yaml").read_bytes()).hexdigest()
        == distribution["finalFluxInstanceSha256"]
    )


def test_bootstrap_and_final_flux_instances_differ_only_by_sync_path() -> None:
    runtime_final = _load(_RUNTIME / "flux-instance.yaml")
    runtime_bootstrap = _load(_RUNTIME / "flux-instance-bootstrap.yaml")
    assert runtime_final == _load(_CLUSTER / "flux-instance.yaml")
    assert runtime_bootstrap == _load(_CLUSTER / "flux-instance-bootstrap.yaml")

    assert runtime_final["apiVersion"] == "fluxcd.controlplane.io/v1"
    assert runtime_final["kind"] == "FluxInstance"
    assert runtime_final["metadata"] == {"name": "flux", "namespace": "flux-system"}
    assert _at(runtime_final, "spec", "distribution") == {"version": "2.9.2", "registry": "ghcr.io/fluxcd"}
    assert _at(runtime_final, "spec", "sync", "ref") == "refs/heads/${RUNTIME_CONTROL_BRANCH}"
    assert _at(runtime_final, "spec", "sync", "pullSecret") == "flux-system"
    assert _at(runtime_final, "spec", "sync", "path") == "infra/k8s/gitops/clusters/local"
    assert _at(runtime_bootstrap, "spec", "sync", "path") == "infra/k8s/gitops/clusters/local/bootstrap"

    bootstrap_as_final = _with_value(
        runtime_bootstrap,
        ("spec", "sync", "path"),
        _at(runtime_final, "spec", "sync", "path"),
    )
    assert bootstrap_as_final == runtime_final
    patches = _list(_at(runtime_final, "spec", "kustomize", "patches"))
    assert len(patches) == 1
    patch = _string(_mapping(patches[0])["patch"])
    assert "name: flux-sops" in patch
    assert "name: nohiki-verification-attempt" in patch


def test_bootstrap_root_is_ordered_before_the_complete_final_root() -> None:
    bootstrap = _load(_CLUSTER / "bootstrap/kustomization.yaml")
    assert bootstrap["resources"] == ["gateway-api-crds.yaml", "registry.yaml"]
    final = _load(_CLUSTER / "kustomization.yaml")
    assert final["resources"] == [
        "bootstrap/",
        "infrastructure.yaml",
        "runtime-secrets.yaml",
        "platform.yaml",
        "observability.yaml",
        "health.yaml",
        "verification-api.yaml",
        "verification-playwright.yaml",
        "flux-instance.yaml",
    ]


def test_fallback_install_and_sync_are_offline_private_and_digest_pinned() -> None:
    install = _documents(_RUNTIME / "fallback/install.yaml")
    deployments: dict[str, dict[str, object]] = {}
    for document in install:
        if document.get("kind") == "Deployment":
            deployments[_string_at(document, "metadata", "name")] = document
    assert set(deployments) == {
        "source-controller",
        "kustomize-controller",
        "helm-controller",
        "notification-controller",
    }
    for deployment in deployments.values():
        containers = _list(_at(deployment, "spec", "template", "spec", "containers"))
        assert len(containers) == 1
        image = _string(_mapping(containers[0])["image"])
        assert re.fullmatch(r"ghcr\.io/fluxcd/[a-z-]+@sha256:[0-9a-f]{64}", image)

    sync_text = (_RUNTIME / "fallback/sync.yaml").read_text(encoding="utf-8")
    assert sync_text.count("${RUNTIME_CONTROL_BRANCH}") == 1
    source, root = _documents(_RUNTIME / "fallback/sync.yaml")
    assert source["kind"] == "GitRepository"
    assert _string_at(source, "spec", "url").startswith("ssh://")
    assert _at(source, "spec", "secretRef") == {"name": "flux-system"}
    assert root["kind"] == "Kustomization"
    assert _at(root, "spec", "path") == "./infra/k8s/gitops/clusters/local"
    assert _at(root, "spec", "prune") is True
    assert _at(root, "spec", "decryption") == {"provider": "sops", "secretRef": {"name": "flux-sops"}}


def test_operator_failure_selects_core_once_without_retry_in_both_drills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    monkeypatch.setenv("NOHIKI_RUNTIME_CONTROL_BRANCH", "runtime-control/local/test")
    monkeypatch.setenv("NOHIKI_REVIEWED_TOPIC_SHA", "a" * 40)
    monkeypatch.setattr(runner, "validate_runtime_control", lambda *_: None)
    monkeypatch.setattr(runner, "render_branch_manifest", lambda *_: "b" * 64)
    operator_calls: list[str] = []
    core_calls: list[str] = []

    def failed_operator(*_: object) -> bool:
        operator_calls.append("operator")
        return False

    def core(*_: object) -> None:
        core_calls.append("core")

    monkeypatch.setattr(runner, "operator_install_once", failed_operator)
    monkeypatch.setattr(runner, "install_core_runtime", core)
    kubeconfig = tmp_path / "kubeconfig"

    operator_to_core = runner.qualify_flux_runtime(kubeconfig, tmp_path, "operator-to-core")
    assert operator_to_core["selected"] == "core"
    assert operator_calls == ["operator"]
    assert core_calls == ["core"]

    operator_calls.clear()
    core_calls.clear()
    core_to_operator = runner.qualify_flux_runtime(kubeconfig, tmp_path, "core-to-operator")
    assert core_to_operator["selected"] == "core"
    assert operator_calls == ["operator"]
    assert core_calls == ["core", "core"]


def test_successful_operator_is_selected_without_invoking_core_fallback() -> None:
    runner = _load_runner()
    calls: list[str] = []

    def operator() -> bool:
        calls.append("operator")
        return True

    def core() -> None:
        calls.append("core")

    assert runner.select_flux_runtime(operator, core) == "operator"
    assert calls == ["operator"]

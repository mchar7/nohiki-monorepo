from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

import yaml

_ROOT = Path(__file__).resolve().parents[4]
_RUNTIME = _ROOT / "infra/k8s/flux-runtime"
_CLUSTER = _ROOT / "infra/k8s/gitops/clusters/local"
_ARTIFACTS = _RUNTIME / "runtime-artifacts.py"
_CONFIGMAP = _RUNTIME / "attempt-configmap.py"


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _load(path: Path) -> dict[str, object]:
    return _mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def _at(value: object, *path: str) -> object:
    current = value
    for key in path:
        current = _mapping(current)[key]
    return current


def _artifact_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(_ARTIFACTS), *args),
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env={key: value for key, value in os.environ.items() if key not in {"VIRTUAL_ENV", "PROJECT_ROOT"}},
    )


def test_artifact_verifier_replays_the_digest_pinned_operator_recipe() -> None:
    result = _artifact_command("verify")
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert (
        record["chartLayerSha256"]
        == hashlib.sha256((_RUNTIME / "vendor/flux-operator-0.55.0.tgz").read_bytes()).hexdigest()
    )
    assert (
        record["operatorInstallSha256"] == hashlib.sha256((_RUNTIME / "operator-install.yaml").read_bytes()).hexdigest()
    )
    assert (
        record["operatorImageDigest"]
        == "sha256:"
        + hashlib.sha256((_RUNTIME / "vendor/flux-operator-v0.55.0.oci-index.json").read_bytes()).hexdigest()
    )

    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "operator-install.yaml"
        generated = _artifact_command("generate-operator", "--output", str(output))
        assert generated.returncode == 0, generated.stderr
        assert output.read_bytes() == (_RUNTIME / "operator-install.yaml").read_bytes()


def test_artifact_lock_derives_chart_and_operator_digests_from_upstream_oci_bytes() -> None:
    lock = _load(_RUNTIME / "artifacts.lock.yaml")
    chart_manifest_path = _ROOT / str(_at(lock, "chart", "ociManifestPath"))
    chart_manifest = json.loads(chart_manifest_path.read_text(encoding="utf-8"))
    layer = chart_manifest["layers"][0]
    chart = _RUNTIME / "vendor/flux-operator-0.55.0.tgz"
    assert (
        _at(lock, "chart", "ociManifestDigest")
        == "sha256:" + hashlib.sha256(chart_manifest_path.read_bytes()).hexdigest()
    )
    assert layer["digest"] == "sha256:" + hashlib.sha256(chart.read_bytes()).hexdigest()
    assert layer["size"] == chart.stat().st_size

    operator_index_path = _RUNTIME / "vendor/flux-operator-v0.55.0.oci-index.json"
    operator_index = json.loads(operator_index_path.read_text(encoding="utf-8"))
    index_digest = "sha256:" + hashlib.sha256(operator_index_path.read_bytes()).hexdigest()
    amd64 = [
        item for item in operator_index["manifests"] if item.get("platform") == {"architecture": "amd64", "os": "linux"}
    ]
    assert len(amd64) == 1
    assert _at(lock, "images", "operator", "indexOrImageDigest") == index_digest
    assert _at(lock, "images", "operator", "platformManifestDigest") == amd64[0]["digest"]
    reference = _at(lock, "images", "operator", "reference")
    assert isinstance(reference, str)
    assert reference.endswith("@" + index_digest)


def test_attempt_configmap_producer_closes_the_mandatory_substitution_input() -> None:
    revision = "1" * 40
    lock_digest = hashlib.sha256((_RUNTIME / "artifacts.lock.yaml").read_bytes()).hexdigest()
    result = subprocess.run(
        (
            sys.executable,
            str(_CONFIGMAP),
            "--attempt-suffix",
            "a00000003-1234abcd",
            "--runtime-control-branch",
            "runtime-control/local/attempt-3",
            "--source-head-sha",
            revision,
            "--source-reviewed-sha",
            revision,
            "--source-remote-sha",
            revision,
            "--artifact-lock-sha256",
            lock_digest,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "apiVersion": "v1",
        "data": {
            "NOHIKI_ARTIFACT_LOCK_SHA256": lock_digest,
            "NOHIKI_ATTEMPT_SUFFIX": "a00000003-1234abcd",
            "RUNTIME_CONTROL_BRANCH": "runtime-control/local/attempt-3",
            "NOHIKI_SOURCE_HEAD_SHA": revision,
            "NOHIKI_SOURCE_REMOTE_SHA": revision,
            "NOHIKI_SOURCE_REVIEWED_SHA": revision,
        },
        "kind": "ConfigMap",
        "metadata": {"name": "nohiki-verification-attempt", "namespace": "flux-system"},
    }

    mismatched = subprocess.run(
        (
            sys.executable,
            str(_CONFIGMAP),
            "--attempt-suffix",
            "a00000003-1234abcd",
            "--runtime-control-branch",
            "runtime-control/local/attempt-3",
            "--source-head-sha",
            revision,
            "--source-reviewed-sha",
            "2" * 40,
            "--source-remote-sha",
            revision,
            "--artifact-lock-sha256",
            lock_digest,
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert mismatched.returncode != 0


def test_both_flux_instances_require_the_produced_input_and_only_their_roots_differ() -> None:
    final = _load(_RUNTIME / "flux-instance.yaml")
    bootstrap = _load(_RUNTIME / "flux-instance-bootstrap.yaml")
    assert (_RUNTIME / "flux-instance.yaml").read_bytes() == (_CLUSTER / "flux-instance.yaml").read_bytes()
    assert (_RUNTIME / "flux-instance-bootstrap.yaml").read_bytes() == (
        _CLUSTER / "flux-instance-bootstrap.yaml"
    ).read_bytes()
    assert _at(final, "spec", "sync", "path") == "infra/k8s/gitops/clusters/local"
    assert _at(bootstrap, "spec", "sync", "path") == "infra/k8s/gitops/clusters/local/bootstrap"
    _mapping(_at(bootstrap, "spec", "sync"))["path"] = _at(final, "spec", "sync", "path")
    assert bootstrap == final
    for instance in (final, _load(_RUNTIME / "flux-instance-bootstrap.yaml")):
        patches = _at(instance, "spec", "kustomize", "patches")
        assert isinstance(patches, list)
        assert len(patches) == 1
        patch_entry = _mapping(patches[0])
        patch = yaml.safe_load(str(patch_entry["patch"]))
        assert isinstance(patch, list)
        post_build = next(_mapping(item) for item in patch if _mapping(item).get("path") == "/spec/postBuild")
        post_build_value = _mapping(post_build["value"])
        assert post_build_value["substituteFrom"] == [
            {"kind": "ConfigMap", "name": "nohiki-verification-attempt", "optional": False}
        ]


def test_full_root_preserves_publication_and_ordered_verification_dependencies() -> None:
    bootstrap = _load(_CLUSTER / "bootstrap/kustomization.yaml")
    final = _load(_CLUSTER / "kustomization.yaml")
    assert bootstrap["resources"] == ["gateway-api-crds.yaml", "registry.yaml"]
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
    assert _at(_load(_CLUSTER / "infrastructure.yaml"), "spec", "dependsOn") == [{"name": "gateway-api-crds"}]
    assert _at(_load(_CLUSTER / "platform.yaml"), "spec", "dependsOn") == [
        {"name": "infrastructure"},
        {"name": "runtime-secrets"},
        {"name": "registry"},
    ]
    assert _at(_load(_CLUSTER / "health.yaml"), "spec", "dependsOn") == [{"name": "observability"}]
    assert _at(_load(_CLUSTER / "verification-api.yaml"), "spec", "dependsOn") == [{"name": "health-verification"}]
    assert _at(_load(_CLUSTER / "verification-playwright.yaml"), "spec", "dependsOn") == [{"name": "api-verification"}]


def _nft_command(policy: Path, unshare: str | None) -> tuple[str, ...]:
    nft = shutil.which("nft")
    if nft is not None:
        parser = (nft, "-c", "-f", str(policy))
        if unshare is None:
            return parser
        return (unshare, "--user", "--map-root-user", "--net", *parser)
    command = ("nix", "shell", "nixpkgs#nftables", "-c")
    if unshare is None:
        return (*command, "nft", "-c", "-f", str(policy))
    return (
        *command,
        unshare,
        "--user",
        "--map-root-user",
        "--net",
        "nft",
        "-c",
        "-f",
        str(policy),
    )


def _check_nft_policy(
    policy: Path,
    *,
    unshare: str = "unshare",
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        _nft_command(policy, unshare),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    stderr = result.stderr.casefold()
    if (
        result.returncode != 0
        and "unshare:" in stderr
        and ("operation not permitted" in stderr or "permission denied" in stderr)
    ):
        return subprocess.run(
            _nft_command(policy, None),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    return result


def test_offline_policy_is_accepted_by_the_real_nft_parser() -> None:
    policy = _RUNTIME / "offline-egress.nft"
    result = _check_nft_policy(policy)
    assert result.returncode == 0, result.stderr
    text = policy.read_text(encoding="utf-8")
    assert text.count("policy drop;") == 2
    assert text.count("counter reject") == 2


def test_offline_policy_fallback_rejects_invalid_syntax(tmp_path: Path) -> None:
    unshare_denied = tmp_path / "unshare-denied"
    unshare_denied.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'unshare: write failed /proc/self/uid_map: Operation not permitted' >&2\nexit 1\n",
        encoding="utf-8",
    )
    unshare_denied.chmod(0o700)
    broken = tmp_path / "broken.nft"
    broken.write_text(
        (_RUNTIME / "offline-egress.nft").read_text(encoding="utf-8") + "\nthis is invalid\n",
        encoding="utf-8",
    )
    result = _check_nft_policy(broken, unshare=str(unshare_denied))
    assert result.returncode != 0
    assert "syntax error" in result.stderr.casefold()

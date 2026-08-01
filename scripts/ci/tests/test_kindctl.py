from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = _ROOT / "infra/k8s/local/kindctl"
_CONFIG = _ROOT / "infra/k8s/local/kind.yaml"


def _load_runner() -> ModuleType:
    name = f"kindctl_test_{id(object())}"
    loader = importlib.machinery.SourceFileLoader(name, str(_RUNNER))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _completed(argv: Sequence[str], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), returncode, stdout, "")


def test_kind_config_is_the_exact_pinned_single_node_contract() -> None:
    assert (
        _CONFIG.read_text(encoding="utf-8")
        == """kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  apiServerAddress: "127.0.0.1"
  disableDefaultCNI: false
containerdConfigPatches:
  - |-
    [plugins."io.containerd.grpc.v1.cri".registry]
      config_path = "/etc/containerd/certs.d"
nodes:
  - role: control-plane
    image: kindest/node:v1.36.1@sha256:3489c7674813ba5d8b1a9977baea8a6e553784dab7b84759d1014dbd78f7ebd5
"""
    )


def test_unknown_commands_and_missing_observer_separator_are_rejected() -> None:
    runner = _load_runner()
    with pytest.raises(SystemExit):
        runner.parse_arguments(["unknown"])
    arguments = runner.parse_arguments(["observe", "--", "--attempt", "1"])
    assert arguments.observer_args == ["--", "--attempt", "1"]
    with pytest.raises(runner.KindctlError, match="argument separator"):
        runner.main(["observe"])


def test_mutation_attempt_directory_is_absolute_owned_real_and_mode_0700(tmp_path: Path) -> None:
    runner = _load_runner()
    with pytest.raises(runner.KindctlError, match="absolute"):
        runner.validate_attempt_dir("relative")
    attempt = tmp_path / "attempt-1"
    attempt.mkdir(mode=0o700)
    assert runner.validate_attempt_dir(str(attempt)) == attempt
    attempt.chmod(0o755)
    with pytest.raises(runner.KindctlError, match="0700"):
        runner.validate_attempt_dir(str(attempt))


def test_create_argv_is_scoped_podman_and_bounded(tmp_path: Path) -> None:
    runner = _load_runner()
    kubeconfig = tmp_path / "runtime/kubeconfig"
    assert runner.create_argv(kubeconfig) == (
        "systemd-run",
        "--scope",
        "--user",
        "-p",
        "Delegate=yes",
        "env",
        "KIND_EXPERIMENTAL_PROVIDER=podman",
        f"KUBECONFIG={kubeconfig}",
        "kind",
        "create",
        "cluster",
        "--name",
        "nohiki",
        "--config",
        str(_CONFIG),
        "--kubeconfig",
        str(kubeconfig),
        "--wait",
        "120s",
    )
    assert runner.CREATE_TIMEOUT == runner.DELETE_TIMEOUT == 120


def test_node_repair_finishes_every_sysctl_before_one_kindnet_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if command[:4] == ("kind", "get", "nodes", "--name"):
            return _completed(argv, "node-a\nnode-b\n")
        if "sysctl" in command and "-n" in command:
            return _completed(argv, "0\n")
        return _completed(argv)

    def fake_json(argv: Sequence[str], **_kwargs: object) -> list[dict[str, Any]]:
        node = str(tuple(argv)[-1])
        return [{"Id": f"id-{node}", "State": {"StartedAt": f"start-{node}"}}]

    monkeypatch.setattr(runner, "run_command", fake_run)
    monkeypatch.setattr(runner, "command_json", fake_json)
    measurements = runner.repair_nodes(tmp_path / "kubeconfig")
    restart = next(index for index, call in enumerate(calls) if call[-2:] == ("restart", "daemonset/kindnet"))
    sysctl_reads = [index for index, call in enumerate(calls) if "sysctl" in call]
    assert sysctl_reads
    assert max(sysctl_reads) < restart
    assert sum(call[-2:] == ("restart", "daemonset/kindnet") for call in calls) == 1
    assert [item["name"] for item in measurements] == ["node-a", "node-b"]
    assert all(item["arpIgnoreAll"] == item["arpIgnoreDefault"] == "0" for item in measurements)


def test_node_pid_limit_must_be_a_recorded_positive_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: [{"HostConfig": {"PidsLimit": 2048}}],
    )
    assert runner.require_node_pid_limits(["nohiki-control-plane"]) == {"nohiki-control-plane": 2048}
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: [{"HostConfig": {"PidsLimit": 0}}],
    )
    with pytest.raises(runner.KindctlError, match="positive integer"):
        runner.require_node_pid_limits(["nohiki-control-plane"])


def test_registry_hosts_copy_uses_exact_bytes_mode_hash_and_annotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []
    expected_hash = __import__("hashlib").sha256(runner.REGISTRY_HOSTS).hexdigest()

    def fake_run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if "stat" in command:
            return _completed(argv, "644\n")
        if "sha256sum" in command:
            return _completed(argv, f"{expected_hash}  hosts.toml\n")
        return _completed(argv)

    monkeypatch.setattr(runner, "run_command", fake_run)
    assert runner.install_registry_hosts(tmp_path / "kubeconfig", ["nohiki-control-plane"]) == expected_hash
    copy_call = next(call for call in calls if call[:2] == ("podman", "cp"))
    assert not Path(copy_call[2]).exists()
    assert copy_call[3] == "nohiki-control-plane:/etc/containerd/certs.d/localhost:5000/hosts.toml"
    assert any(call[-2:] == (f"nohiki.io/hosts-sha256={expected_hash}", "--overwrite") for call in calls)
    assert (
        runner.REGISTRY_HOSTS
        == b"""server = "http://127.0.0.1:30500"

[host."http://127.0.0.1:30500"]
  capabilities = ["pull", "resolve"]
  skip_verify = true
"""
    )


def test_storage_probe_reuses_the_bound_claim_and_requires_pv_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    manifests: list[str] = []
    calls: list[tuple[str, ...]] = []
    nonce = ""

    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal nonce
        command = tuple(argv)
        calls.append(command)
        if command[-3:] == ("apply", "-f", "-"):
            manifest = str(kwargs["input_text"])
            manifests.append(manifest)
            if "nohiki-storage-writer" in manifest:
                marker = "printf %s "
                nonce = manifest.split(marker, 1)[1].split(" >", 1)[0]
            return _completed(argv)
        if "logs" in command:
            return _completed(argv, f"{nonce}\n")
        if {"get", "pvc", "nohiki-storage-probe"}.issubset(command):
            return _completed(argv, json.dumps({"spec": {"volumeName": "pv-probe"}}))
        return _completed(argv)

    monkeypatch.setattr(runner, "run_command", fake_run)
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "spec": {"volumeName": "pv-probe"},
            "status": {"capacity": {"storage": "64Mi"}, "phase": "Bound"},
        },
    )
    result = runner.storage_probe(tmp_path / "kubeconfig")
    assert result == {
        "accessModes": "ReadWriteOnce",
        "capacity": "64Mi",
        "persistentVolume": "pv-probe",
        "storageClass": "standard",
    }
    assert len(manifests) == 2
    assert all("claimName: nohiki-storage-probe" in manifest for manifest in manifests)
    assert "storageClassName: standard" in manifests[0]
    assert any("--for=delete" in call and "pv/pv-probe" in call for call in calls)


def test_residue_inventory_detects_every_nohiki_owned_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    runtime = tmp_path / "nohiki-kind"
    runtime.mkdir()
    (runtime / "proxy-state.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "runtime_root", lambda: runtime)
    monkeypatch.setattr(runner, "kind_clusters", lambda: ["nohiki"])
    monkeypatch.setattr(runner, "kube_contexts", lambda _path: ["kind-nohiki"])

    def fake_podman(argv: Sequence[str]) -> list[dict[str, str]]:
        return [{"Names": "nohiki-control-plane"}] if "ps" in argv else [{"Name": "nohiki-volume"}]

    def fake_run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if tuple(argv)[:3] == ("podman", "network", "inspect"):
            return _completed(argv, json.dumps([{"containers": {"id": {"name": "nohiki-control-plane"}}}]))
        return _completed(argv, "{}")

    monkeypatch.setattr(runner, "podman_json", fake_podman)
    monkeypatch.setattr(runner, "run_command", fake_run)
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    inventory = runner.collect_residue(kubeconfig)
    assert all(inventory.values())
    with pytest.raises(runner.KindctlError, match="residue remains"):
        runner.require_no_residue(kubeconfig)


def test_delete_binding_rejects_a_replaced_runner_kubeconfig(tmp_path: Path) -> None:
    runner = _load_runner()
    attempt = tmp_path / "attempt-1"
    runtime = attempt / "runtime"
    runtime.mkdir(parents=True)
    kubeconfig = runtime / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    kubeconfig.chmod(0o600)
    metadata = kubeconfig.stat()
    measurement = {
        "kubeconfig": {
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": "0600",
            "owner": metadata.st_uid,
            "path": str(kubeconfig),
        }
    }
    runner.write_exclusive(attempt / "runner-measurements.json", measurement)
    runner.write_exclusive(
        attempt / "runner-measurements.sha256.json",
        {"sha256": runner.sha256_file(attempt / "runner-measurements.json")},
    )
    runner.validate_kubeconfig_binding(attempt, kubeconfig)
    replacement = runtime / "replacement-kubeconfig"
    replacement.write_text("apiVersion: v1\n", encoding="utf-8")
    replacement.chmod(0o600)
    assert replacement.stat().st_ino != metadata.st_ino
    replacement.replace(kubeconfig)
    with pytest.raises(runner.KindctlError, match="identity changed"):
        runner.validate_kubeconfig_binding(attempt, kubeconfig)


def test_delete_uses_scoped_kind_delete_then_removes_only_runner_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    attempt = tmp_path / "attempt-1"
    runtime = attempt / "runtime"
    runtime.mkdir(parents=True)
    runtime.chmod(0o700)
    kubeconfig = runtime / "kubeconfig"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    kubeconfig.chmod(0o600)
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if command[:3] == ("podman", "network", "inspect"):
            return _completed(argv, returncode=1)
        return _completed(argv)

    monkeypatch.setattr(runner, "run_command", fake_run)
    monkeypatch.setattr(runner, "diagnostics", lambda *_args: {})
    monkeypatch.setattr(runner, "kind_clusters", list)
    monkeypatch.setattr(runner, "validate_kubeconfig_binding", lambda *_args: None)
    runner.delete(attempt)
    delete_call = next(call for call in calls if "delete" in call and "cluster" in call)
    assert delete_call[:6] == ("systemd-run", "--scope", "--user", "-p", "Delegate=yes", "env")
    assert delete_call[-5:] == ("cluster", "--name", "nohiki", "--kubeconfig", str(kubeconfig))
    assert not runtime.exists()

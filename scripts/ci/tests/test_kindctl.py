from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
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


def _install_lifecycle_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_create_once: bool = False,
) -> tuple[Path, Path]:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    state = tmp_path / "cluster-state"
    log = tmp_path / "systemd-run.jsonl"
    failure = tmp_path / "fail-create-once"
    if fail_create_once:
        failure.touch()
    program = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
state = Path(os.environ["FAKE_KIND_STATE"])
log = Path(os.environ["FAKE_COMMAND_LOG"])
failure = Path(os.environ["FAKE_CREATE_FAILURE"])
if name == "kind" and args == ["get", "clusters"]:
    if state.exists():
        print("nohiki")
elif name == "kubectl":
    if "config" not in args:
        raise SystemExit(1)
elif name == "podman":
    if args[:2] == ["network", "inspect"]:
        raise SystemExit(1)
    print("[]")
elif name == "systemd-run":
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(args) + "\\n")
    if "create" in args:
        if failure.exists():
            failure.unlink()
            raise SystemExit(17)
        state.touch()
    elif "delete" in args:
        state.unlink(missing_ok=True)
"""
    for name in ("kind", "kubectl", "podman", "systemd-run"):
        binary = binary_dir / name
        binary.write_text(program, encoding="utf-8")
        binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_KIND_STATE", str(state))
    monkeypatch.setenv("FAKE_COMMAND_LOG", str(log))
    monkeypatch.setenv("FAKE_CREATE_FAILURE", str(failure))
    (tmp_path / "xdg").mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    return state, log


def _stub_create_acceptance(runner: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(runner, "kind_modules_override", lambda: None)
    monkeypatch.setattr(runner, "validate_cluster", lambda _path: ("cluster-uid", ["nohiki-control-plane"]))
    monkeypatch.setattr(
        runner,
        "repair_nodes",
        lambda _path: [{"name": "nohiki-control-plane"}],
    )
    monkeypatch.setattr(
        runner,
        "require_node_pid_limits",
        lambda _nodes: {"nohiki-control-plane": 2048},
    )
    monkeypatch.setattr(runner, "require_storage_class", lambda _path: None)
    dns = {"ready": False}

    def mark_dns_ready(_path: Path) -> None:
        dns["ready"] = True

    def require_ready_dns(_path: Path) -> dict[str, bool]:
        if not dns["ready"]:
            message = "network probe ran before CoreDNS readiness"
            raise runner.KindctlError(message)
        return {"dns": True}

    monkeypatch.setattr(runner, "require_cluster_dns_ready", mark_dns_ready)
    monkeypatch.setattr(runner, "network_probe", require_ready_dns)
    monkeypatch.setattr(
        runner,
        "storage_probe",
        lambda _path: {"capacity": "64Mi"},
    )


def _attempt(tmp_path: Path, name: str = "attempt-1") -> Path:
    attempt = tmp_path / name
    attempt.mkdir(mode=0o700)
    return attempt


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


def test_kind_modules_override_preserves_conventional_hosts_and_fails_loudly(tmp_path: Path) -> None:
    runner = _load_runner()
    conventional = tmp_path / "lib/modules"
    booted = tmp_path / "run/booted/modules"
    current = tmp_path / "run/current/modules"
    conventional.mkdir(parents=True)
    assert runner.kind_modules_override((conventional, booted, current), "test-release") is None

    conventional.rmdir()
    (booted / "test-release").mkdir(parents=True)
    assert runner.kind_modules_override((conventional, booted, current), "test-release") == booted.resolve()

    (booted / "test-release").rmdir()
    with pytest.raises(runner.KindctlError) as raised:
        runner.kind_modules_override((conventional, booted, current), "test-release")
    message = str(raised.value)
    assert all(str(path) in message for path in (conventional, booted, current))


def test_create_path_executes_provider_rewrite_for_missing_lib_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    real_bin = tmp_path / "real-bin"
    real_bin.mkdir()
    log = tmp_path / "podman-argv.json"
    podman = real_bin / "podman"
    podman.write_text(
        f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

Path({json.dumps(str(log))}).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
""",
        encoding="utf-8",
    )
    podman.chmod(0o755)
    monkeypatch.setenv("PATH", f"{real_bin}:{os.environ['PATH']}")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    modules = tmp_path / "host-modules"
    modules.mkdir()

    provider_bin = runner.install_kind_provider_wrapper(runtime, modules)
    create_command = runner.create_argv(runtime / "kubeconfig", provider_bin)
    path_assignment = next(value for value in create_command if value.startswith("PATH="))
    environment = os.environ | {"PATH": path_assignment.removeprefix("PATH=")}
    subprocess.run(
        ["podman", "create", "--volume", "/lib/modules:/lib/modules:ro", "node"],
        check=True,
        env=environment,
    )

    observed = json.loads(log.read_text(encoding="utf-8"))
    assert observed == ["create", "--volume", f"{modules}:/lib/modules:ro", "node"]


def test_preflight_accepts_pinned_client_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []
    outputs = {
        ("kind", "version"): "kind v0.32.0 go1.25.7 linux/amd64\n",
        ("flux", "version", "--client"): "flux: v2.9.2\n",
        ("flux-operator", "version", "--client"): "client: 0.55.0\n",
    }

    def fake_run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        command = tuple(argv)
        calls.append(command)
        if command not in outputs:
            message = "unexpected version command"
            raise runner.KindctlError(message)
        return _completed(argv, outputs[command])

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/bin/tool")
    monkeypatch.setattr(runner, "run_command", fake_run)
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(runner.KindctlError("versions passed")),
    )
    with pytest.raises(runner.KindctlError, match="versions passed"):
        runner.preflight()
    assert calls == [
        ("kind", "version"),
        ("flux", "version", "--client"),
        ("flux-operator", "version", "--client"),
    ]


def test_create_executes_the_scoped_command_under_its_own_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    state, log = _install_lifecycle_commands(tmp_path, monkeypatch)
    _stub_create_acceptance(runner, monkeypatch)
    attempt = _attempt(tmp_path)

    assert runner.main(["--attempt-dir", str(attempt), "create"]) == 0

    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    create_event = next(event for event in events if "create" in event)
    kubeconfig = attempt / "runtime/kubeconfig"
    assert create_event == [
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
    ]
    assert state.exists()
    assert json.loads((attempt / "commands/create.json").read_text())["result"] == "passed"
    assert (attempt / "runner-measurements.json").is_file()
    runner.main(["--attempt-dir", str(attempt), "delete"])


def test_failed_create_cleans_up_and_the_same_attempt_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    state, _log = _install_lifecycle_commands(tmp_path, monkeypatch, fail_create_once=True)
    _stub_create_acceptance(runner, monkeypatch)
    attempt = _attempt(tmp_path)

    with pytest.raises(runner.KindctlError, match="command failed \\(17\\)"):
        runner.main(["--attempt-dir", str(attempt), "create"])
    assert not (attempt / "runtime").exists()
    assert not state.exists()
    assert json.loads((attempt / "commands/create.json").read_text())["exitCode"] == 1

    assert runner.main(["--attempt-dir", str(attempt), "create"]) == 0
    retry = json.loads((attempt / "commands/create-2.json").read_text())
    assert retry["exitCode"] == 0
    assert retry["result"] == "passed"
    runner.main(["--attempt-dir", str(attempt), "delete"])


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


def test_cluster_dns_gate_waits_for_rollout_and_every_coredns_pod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []
    timeouts: list[int] = []

    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(argv))
        timeout = kwargs["timeout"]
        assert isinstance(timeout, int)
        timeouts.append(timeout)
        return _completed(argv)

    monkeypatch.setattr(runner, "run_command", fake_run)
    kubeconfig = tmp_path / "kubeconfig"
    runner.require_cluster_dns_ready(kubeconfig)

    prefix = ("kubectl", "--kubeconfig", str(kubeconfig), "-n", "kube-system")
    assert calls == [
        (*prefix, "rollout", "status", "deployment/coredns", "--timeout=120s"),
        (*prefix, "wait", "--for=condition=Ready", "pod", "-l", "k8s-app=kube-dns", "--timeout=120s"),
    ]
    assert timeouts == [125, 125]


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


def test_delete_converges_populated_runtime_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    state, log = _install_lifecycle_commands(tmp_path, monkeypatch)
    _stub_create_acceptance(runner, monkeypatch)
    attempt = _attempt(tmp_path)
    runner.main(["--attempt-dir", str(attempt), "create"])
    cache = attempt / "runtime/cache"
    cache.mkdir()
    (cache / "partial-state").write_text("owned\n", encoding="utf-8")

    assert runner.main(["--attempt-dir", str(attempt), "delete"]) == 0
    assert not state.exists()
    assert not (attempt / "runtime").exists()
    assert json.loads((attempt / "commands/delete.json").read_text())["result"] == "passed"

    assert runner.main(["--attempt-dir", str(attempt), "delete"]) == 0
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    delete_events = [event for event in events if "delete" in event]
    assert len(delete_events) == 1
    assert json.loads((attempt / "commands/delete-2.json").read_text())["result"] == "passed"

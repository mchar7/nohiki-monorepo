from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import ipaddress
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

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
    monkeypatch.setattr(runner, "start_memory_sampler", lambda _attempt: None)
    monkeypatch.setattr(runner, "mark_memory_sampler_created", lambda _attempt: None)
    monkeypatch.setattr(runner, "kind_modules_override", lambda: None)
    monkeypatch.setattr(runner, "require_llm_proxy_env_file", lambda: Path("/secure/proxy.env"))
    monkeypatch.setattr(
        runner,
        "write_llm_proxy_values",
        lambda *_: Path("/secure/owner-model-egress.values.json"),
    )
    monkeypatch.setattr(runner, "install_llm_proxy_source", lambda *_: {})
    monkeypatch.setattr(
        runner,
        "validate_cluster",
        lambda _path: ("cluster-uid", ["nohiki-control-plane"], {"nohiki-control-plane": 250}),
    )
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
    provisioner = {"ready": False}

    def mark_provisioner_ready(_path: Path) -> None:
        provisioner["ready"] = True

    def require_ready_provisioner(_path: Path) -> dict[str, str]:
        if not provisioner["ready"]:
            message = "storage probe ran before provisioner recreation"
            raise runner.KindctlError(message)
        return {"capacity": "64Mi"}

    monkeypatch.setattr(runner, "recreate_storage_provisioner", mark_provisioner_ready)
    monkeypatch.setattr(runner, "storage_probe", require_ready_provisioner)


def _attempt(tmp_path: Path, name: str = "attempt-1") -> Path:
    attempt = tmp_path / name
    attempt.mkdir(mode=0o700)
    return attempt


def test_kind_config_has_independently_sized_single_node_capacity() -> None:
    configuration = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    assert configuration["kind"] == "Cluster"
    assert configuration["apiVersion"] == "kind.x-k8s.io/v1alpha4"
    assert configuration["networking"] == {
        "apiServerAddress": "127.0.0.1",
        "disableDefaultCNI": False,
    }
    assert len(configuration["containerdConfigPatches"]) == 1
    assert 'config_path = "/etc/containerd/certs.d"' in configuration["containerdConfigPatches"][0]
    assert len(configuration["nodes"]) == 1
    node = configuration["nodes"][0]
    assert node["role"] == "control-plane"
    assert "@sha256:" in node["image"]
    kubelet_documents = [
        yaml.safe_load(patch)
        for patch in node["kubeadmConfigPatches"]
        if yaml.safe_load(patch).get("kind") == "KubeletConfiguration"
    ]
    assert len(kubelet_documents) == 1
    observed_running = 27
    observed_pending = 70
    doubled_observed_total = 2 * (observed_running + observed_pending)
    required_capacity = ((doubled_observed_total + 9) // 10) * 10
    assert kubelet_documents[0]["maxPods"] >= required_capacity


@pytest.mark.parametrize(("capacity", "expected_capacity"), [(110, None), (211, 211)])
def test_cluster_validation_observes_live_allocatable_pods(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capacity: int,
    expected_capacity: int | None,
) -> None:
    runner = _load_runner()
    kubeconfig = tmp_path / "kubeconfig"
    monkeypatch.setattr(
        runner,
        "run_command",
        lambda argv, **_kwargs: _completed(argv, stdout="kind-nohiki\n"),
    )

    def fake_json(argv: Sequence[str], **_kwargs: object) -> dict[str, Any]:
        command = tuple(argv)
        if "--raw=/version" in command:
            return {"gitVersion": runner.KUBERNETES_VERSION}
        if "nodes" in command:
            return {
                "items": [
                    {
                        "metadata": {"name": "nohiki-control-plane"},
                        "status": {
                            "allocatable": {"pods": str(capacity)},
                            "conditions": [{"type": "Ready", "status": "True"}],
                        },
                    }
                ]
            }
        return {"metadata": {"uid": "cluster-uid"}}

    monkeypatch.setattr(runner, "command_json", fake_json)
    if expected_capacity is None:
        with pytest.raises(runner.KindctlError, match=f"allocatable Pods {capacity}"):
            runner.validate_cluster(kubeconfig)
        return
    assert runner.validate_cluster(kubeconfig) == (
        "cluster-uid",
        ["nohiki-control-plane"],
        {"nohiki-control-plane": expected_capacity},
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
    assert observed == [
        "create",
        "--pids-limit=16384",
        "--volume",
        f"{modules}:/lib/modules:ro",
        "node",
    ]
    pid_only_runtime = tmp_path / "pid-only-runtime"
    pid_only_runtime.mkdir(mode=0o700)
    pid_only_bin = runner.install_kind_provider_wrapper(pid_only_runtime, None)
    pid_only_path = runner.create_argv(runtime / "kubeconfig", pid_only_bin)
    pid_only_assignment = next(value for value in pid_only_path if value.startswith("PATH="))
    pid_only_environment = os.environ | {"PATH": pid_only_assignment.removeprefix("PATH=")}
    subprocess.run(["podman", "run", "node"], check=True, env=pid_only_environment)
    assert json.loads(log.read_text(encoding="utf-8")) == [
        "run",
        "--pids-limit=16384",
        "node",
    ]


def test_preflight_accepts_pinned_client_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    calls: list[tuple[str, ...]] = []
    outputs = {
        ("kind", "version"): f"kind {runner.KIND_VERSION} go9.9.9 linux/amd64\n",
        ("flux", "version", "--client"): f"flux: v{runner.FLUX_VERSION}\n",
        ("flux-operator", "version", "--client"): f"client: {runner.FLUX_OPERATOR_VERSION}\n",
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


def test_create_rejects_a_missing_proxy_source_before_runtime_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    monkeypatch.delenv(runner.LLM_PROXY_ENV, raising=False)
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(runner, "require_no_residue", lambda *_: None)
    monkeypatch.setattr(runner, "kind_modules_override", lambda: None)

    with pytest.raises(runner.KindctlError, match=runner.LLM_PROXY_ENV):
        runner.create(attempt)

    assert not (attempt / "runtime").exists()


def test_llm_proxy_source_requires_an_owner_only_regular_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    source = tmp_path / "proxy.env"
    source.write_text("LLM_PROXY_SERVER_API_KEY=synthetic\n", encoding="utf-8")
    source.chmod(0o600)
    monkeypatch.setenv(runner.LLM_PROXY_ENV, str(source))

    assert runner.require_llm_proxy_env_file() == source

    source.chmod(0o640)
    with pytest.raises(runner.KindctlError, match="owner-only mode-0600"):
        runner.require_llm_proxy_env_file()


def test_proxy_binding_materializes_only_attempt_local_nonsecret_values(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    host = str(ipaddress.ip_address(0x0A141E28))
    source = tmp_path / "proxy.env"
    source.write_text(
        f"LLM_PROXY_SERVER_BASE_URL=http://{host}:8317/v1\nLLM_PROXY_SERVER_API_KEY=synthetic-credential\n",
        encoding="utf-8",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)

    values = runner.write_llm_proxy_values(runtime, source)

    assert values == runtime / "owner-model-egress.values.json"
    assert values.stat().st_mode & 0o777 == 0o600
    rendered = json.loads(values.read_text(encoding="utf-8"))
    assert rendered == {
        "global": {
            "modelEgress": {
                "destinations": [{"cidr": f"{host}/32", "port": 8317}],
                "providerEndpoints": {
                    "openai-responses": {
                        "host": host,
                        "path": "/v1/responses",
                        "port": 8317,
                        "tls": None,
                    }
                },
            }
        }
    }
    assert "synthetic-credential" not in values.read_text(encoding="utf-8")


def test_create_installs_proxy_credentials_and_required_values_configmap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    kubeconfig = tmp_path / "kubeconfig"
    source = tmp_path / "proxy.env"
    source.write_text(
        "LLM_PROXY_SERVER_API_KEY=synthetic-credential\nLLM_PROXY_SERVER_BASE_URL=http://owner-proxy.example:8317\n",
        encoding="utf-8",
    )
    values = tmp_path / "owner-model-egress.values.json"
    source_sha256 = runner.sha256_file(source)
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        call = tuple(argv)
        calls.append(call)
        if call[-1].startswith("jsonpath="):
            return _completed(argv, f"proxy-secret-uid\t17\tOpaque\t{source_sha256}")
        if call[-1].startswith("go-template="):
            return _completed(argv, "LLM_PROXY_SERVER_BASE_URL\nLLM_PROXY_SERVER_API_KEY\n")
        return _completed(argv)

    monkeypatch.setattr(runner, "run_command", run)

    measurement = runner.install_llm_proxy_source(kubeconfig, source, values)

    assert calls[:3] == [
        (
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "create",
            "namespace",
            "flux-system",
        ),
        (
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "create",
            "namespace",
            "nohiki",
        ),
        (
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "-n",
            "nohiki",
            "create",
            "secret",
            "generic",
            "nohiki-llm-proxy-source",
            f"--from-env-file={source}",
        ),
    ]
    assert calls[-1][-4:] == (
        "create",
        "configmap",
        "nohiki-owner-model-egress-values",
        f"--from-file=values.yaml={values}",
    )
    assert measurement == {
        "keyNames": ["LLM_PROXY_SERVER_API_KEY", "LLM_PROXY_SERVER_BASE_URL"],
        "name": "nohiki-llm-proxy-source",
        "namespace": "nohiki",
        "resourceVersion": "17",
        "sourceFileSha256": source_sha256,
        "type": "Opaque",
        "uid": "proxy-secret-uid",
    }
    assert "synthetic-credential" not in json.dumps(measurement)


def test_interim_memory_guard_fails_below_derived_floor() -> None:
    runner = _load_runner()
    floor = 23 * 1024**3

    with pytest.raises(runner.KindctlError, match="at least 23 GiB available RAM"):
        runner.require_available_memory(floor - 1)

    runner.require_available_memory(floor)

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
        f"PATH={attempt}/runtime/provider-bin:{os.environ['PATH']}",
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
    sampler_events: list[str] = []
    monkeypatch.setattr(runner, "start_memory_sampler", lambda _attempt: sampler_events.append("start"))
    monkeypatch.setattr(runner, "mark_memory_sampler_created", lambda _attempt: sampler_events.append("created"))
    monkeypatch.setattr(runner, "cleanup_memory_sampler", lambda _attempt: sampler_events.append("cleanup"))
    attempt = _attempt(tmp_path)

    with pytest.raises(runner.KindctlError, match="command failed \\(17\\)"):
        runner.main(["--attempt-dir", str(attempt), "create"])
    assert not (attempt / "runtime").exists()
    assert not state.exists()
    assert json.loads((attempt / "commands/create.json").read_text())["exitCode"] == 1
    assert sampler_events == ["start", "cleanup"]

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


def test_storage_provisioner_is_recreated_after_network_convergence(
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
    runner.recreate_storage_provisioner(kubeconfig)

    prefix = ("kubectl", "--kubeconfig", str(kubeconfig), "-n", "local-path-storage")
    assert calls == [
        (*prefix, "rollout", "restart", "deployment/local-path-provisioner"),
        (*prefix, "rollout", "status", "deployment/local-path-provisioner", "--timeout=120s"),
    ]
    assert timeouts == [30, 125]


def test_node_pid_limit_must_cover_failed_campaign_process_census(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: [{"HostConfig": {"PidsLimit": 16384}}],
    )
    assert runner.require_node_pid_limits(["nohiki-control-plane"]) == {"nohiki-control-plane": 16384}
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: [{"HostConfig": {"PidsLimit": 8192}}],
    )
    with pytest.raises(runner.KindctlError, match="at least 16384"):
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


def test_local_render_only_requests_kind_storage_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "items": [{"metadata": {"name": "standard"}}],
        },
    )

    assert runner.require_rendered_storage_classes(tmp_path / "kubeconfig") == ()


def test_rendered_storage_guard_names_every_missing_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "run_command",
        lambda argv, **_kwargs: _completed(
            argv,
            "spec:\n  storageClassName: gone-b\n---\nspec:\n  storageClassName: gone-a\n",
        ),
    )
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "items": [{"metadata": {"name": "standard"}}],
        },
    )

    with pytest.raises(
        runner.KindctlError,
        match="unavailable StorageClasses: gone-a, gone-b",
    ):
        runner.require_rendered_storage_classes(tmp_path / "kubeconfig")


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
    sampler_cleanups: list[Path] = []
    monkeypatch.setattr(runner, "cleanup_memory_sampler", sampler_cleanups.append)
    attempt = _attempt(tmp_path)
    runner.main(["--attempt-dir", str(attempt), "create"])
    cache = attempt / "runtime/cache"
    cache.mkdir()
    (cache / "partial-state").write_text("owned\n", encoding="utf-8")

    assert runner.main(["--attempt-dir", str(attempt), "delete"]) == 0
    assert not state.exists()
    assert not (attempt / "runtime").exists()
    assert json.loads((attempt / "commands/delete.json").read_text())["result"] == "passed"
    assert sampler_cleanups == [attempt]

    assert runner.main(["--attempt-dir", str(attempt), "delete"]) == 0
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    delete_events = [event for event in events if "delete" in event]
    assert len(delete_events) == 1
    assert json.loads((attempt / "commands/delete-2.json").read_text())["result"] == "passed"


def test_runtime_control_git_queries_are_repository_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    branch = "runtime-control/local/test"
    revision = "1" * 40
    calls: list[tuple[str, ...]] = []

    def run(
        argv: Sequence[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        call = tuple(argv)
        calls.append(call)
        if "branch" in call:
            return _completed(argv, stdout=branch + "\n")
        if "rev-parse" in call:
            return _completed(argv, stdout=revision + "\n")
        return _completed(
            argv,
            stdout=f"{revision}\trefs/heads/{branch}\n",
        )

    monkeypatch.setattr(runner, "run_command", run)

    runner.validate_runtime_control(branch, revision)

    assert calls
    assert all(call[:3] == ("git", "-C", str(runner.REPO_ROOT)) for call in calls)


def _stub_publication_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    changed: str = "",
    untracked: str = "",
    rendered: str | None = None,
) -> tuple[ModuleType, Path, Path, list[tuple[str, ...]]]:
    runner = _load_runner()
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    image_foundation = tmp_path / "infra/k8s/local/image_foundation.py"
    image_inventory = tmp_path / "infra/k8s/local/images.json"
    digest_values = tmp_path / "infra/k8s/gitops/platform/local/image-digests.values.yaml"
    artifact_lock = tmp_path / "infra/k8s/flux-runtime/artifacts.lock.yaml"
    model_archive_seed = tmp_path / "infra/k8s/local/model_archive_seed.py"
    semantic_manifest = tmp_path / "data/config/semantic_representation_manifest.json"
    for name, value in (
        ("IMAGE_FOUNDATION", image_foundation),
        ("IMAGE_INVENTORY", image_inventory),
        ("DIGEST_VALUES", digest_values),
        ("ARTIFACT_LOCK", artifact_lock),
        ("MODEL_ARCHIVE_SEED", model_archive_seed),
        ("SEMANTIC_MANIFEST", semantic_manifest),
    ):
        monkeypatch.setattr(runner, name, value)
    prepared_digest_values = (
        json.dumps(
            {
                "global": {
                    "imageDigests": {"service": "sha256:" + "2" * 64},
                    "imageTag": "immutable",
                },
                "imageFoundation": {
                    "images": {
                        "service": {
                            "digest": "sha256:" + "2" * 64,
                            "tag": "sha256-" + "3" * 64,
                        }
                    },
                    "registry": "localhost:5000",
                    "schemaVersion": 1,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    reviewed_root = tmp_path / "reviewed"
    for path, content in (
        (image_foundation, "helper\n"),
        (image_inventory, '{"schemaVersion":1}\n'),
        (digest_values, prepared_digest_values),
        (artifact_lock, "lock\n"),
        (model_archive_seed, "model archive helper\n"),
        (semantic_manifest, "{}\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        reviewed_path = reviewed_root / path.relative_to(tmp_path)
        reviewed_path.parent.mkdir(parents=True, exist_ok=True)
        reviewed_path.write_text(content, encoding="utf-8")

    attempt = _attempt(tmp_path)
    kubeconfig = attempt / "runtime/kubeconfig"
    revision = "1" * 40
    cluster_uid = "1234abcd-0000"
    lock_sha = runner.sha256_file(runner.ARTIFACT_LOCK)
    expected_data = {
        "NOHIKI_ARTIFACT_LOCK_SHA256": lock_sha,
        "NOHIKI_ATTEMPT_SUFFIX": "a00000001-1234abcd",
        "RUNTIME_CONTROL_BRANCH": "runtime-control/local/test",
        "NOHIKI_SOURCE_HEAD_SHA": revision,
        "NOHIKI_SOURCE_REMOTE_SHA": revision,
        "NOHIKI_SOURCE_REVIEWED_SHA": revision,
    }
    monkeypatch.setenv("NOHIKI_RUNTIME_CONTROL_BRANCH", "runtime-control/local/test")
    monkeypatch.setenv("NOHIKI_REVIEWED_TOPIC_SHA", revision)
    monkeypatch.setattr(runner, "validate_runtime_control", lambda *_: None)
    monkeypatch.setattr(
        runner,
        "reviewed_publication_source",
        lambda *_: contextlib.nullcontext(reviewed_root),
    )
    monkeypatch.setattr(
        runner,
        "runtime_binding",
        lambda *_: ({"attempt": 1}, cluster_uid),
    )
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "data": expected_data,
            "metadata": {"uid": "configmap-uid"},
        },
    )
    source_revision = "refs/heads/test@sha1:" + revision
    monkeypatch.setattr(runner, "flux_source_revision", lambda *_: source_revision)
    monkeypatch.setattr(
        runner,
        "wait_kustomization",
        lambda *_: {"status": {"lastAppliedRevision": source_revision}},
    )

    digest_document = {
        "images": {
            "service": {
                "digest": "sha256:" + "2" * 64,
                "tag": "sha256-" + "3" * 64,
            }
        },
        "registry": "localhost:5000",
        "schemaVersion": 1,
    }
    calls: list[tuple[str, ...]] = []

    def run(
        argv: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        call = tuple(argv)
        calls.append(call)
        if call[0] == "git" and "diff" in call:
            return _completed(argv, stdout=changed)
        if call[0] == "git" and "ls-files" in call:
            return _completed(argv, stdout=untracked)
        if call[0] == "uv":
            environment = kwargs.get("env")
            assert isinstance(environment, dict)
            assert any(str(reviewed_root) in argument for argument in call)
            assert environment.get("KUBECONFIG") == str(kubeconfig)
        if "publish" in call:
            digest_path = Path(call[call.index("--digests") + 1])
            digest_path.write_text(json.dumps(digest_document), encoding="utf-8")
        if "prepare" in call:
            (attempt / "model-archives.json").write_text("{}\n", encoding="utf-8")
        if "render-values" in call:
            return _completed(
                argv,
                stdout=rendered if rendered is not None else runner.DIGEST_VALUES.read_text(encoding="utf-8"),
            )
        return _completed(argv)

    monkeypatch.setattr(runner, "run_command", run)
    return runner, attempt, kubeconfig, calls


def test_publish_produces_the_attempt_owned_finalize_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, attempt, kubeconfig, calls = _stub_publication_inputs(
        tmp_path,
        monkeypatch,
    )

    summary = runner.publish_images(kubeconfig, attempt, no_git_write=True)

    record = runner.validate_publication_record(
        attempt,
        attempt / "publication.json",
        "1" * 40,
    )
    assert record["gitWrite"] is False
    assert record["selectedNames"] == ["service"]
    assert record["images"]["service"] == {
        "buildId": "sha256:" + "3" * 64,
        "digest": "sha256:" + "2" * 64,
        "tag": "sha256-" + "3" * 64,
    }
    assert record["clusterUid"] == "1234abcd-0000"
    assert record["configMapUid"] == "configmap-uid"
    assert summary["imageCount"] == 1
    effects = [
        next(item for item in call if item in {"build", "publish", "render-values"})
        for call in calls
        if any(item in {"build", "publish", "render-values"} for item in call)
    ]
    assert effects == ["build", "publish", "render-values"]


@pytest.mark.parametrize(
    "artifact",
    [
        "",
        """# Generated only by the guarded local image publication command.
global:
  imageTag: publish-required
  imageDigests: {}
""",
    ],
)
def test_publish_requires_prepared_digest_artifact_before_cluster_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    runner, attempt, kubeconfig, calls = _stub_publication_inputs(tmp_path, monkeypatch)
    runner.DIGEST_VALUES.write_text(artifact, encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "runtime_binding",
        lambda *_: pytest.fail("runtime binding preceded the artifact precondition"),
    )

    with pytest.raises(runner.KindctlError, match="guarded local image artifact carrier"):
        runner.publish_images(kubeconfig, attempt, no_git_write=True)

    assert not any(effect in call for call in calls for effect in ("build", "publish", "render-values"))


@pytest.mark.parametrize(
    ("changed", "untracked", "rendered", "message"),
    [
        (
            "tracked.txt\n",
            "",
            None,
            "clean reviewed worktree",
        ),
        (
            "",
            "untracked.txt\n",
            None,
            "clean reviewed worktree",
        ),
        (
            "",
            "",
            '{"different":true}\n',
            "does not match the reviewed image digest artifact",
        ),
    ],
)
def test_publish_fails_closed_without_writing_a_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
    untracked: str,
    rendered: str | None,
    message: str,
) -> None:
    runner, attempt, kubeconfig, _calls = _stub_publication_inputs(
        tmp_path,
        monkeypatch,
        changed=changed,
        untracked=untracked,
        rendered=rendered,
    )

    with pytest.raises(runner.KindctlError, match=message):
        runner.publish_images(kubeconfig, attempt, no_git_write=True)

    assert not (attempt / "publication.json").exists()
    assert not (attempt / "publication.sha256.json").exists()


def test_publish_refuses_a_stale_attempt_configmap_before_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, attempt, kubeconfig, calls = _stub_publication_inputs(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "data": {},
            "metadata": {"uid": "configmap-uid"},
        },
    )

    with pytest.raises(runner.KindctlError, match="does not bind this publication"):
        runner.publish_images(kubeconfig, attempt, no_git_write=True)

    assert not any("build" in call for call in calls)


def test_publish_readback_guard_detects_removed_production_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, attempt, kubeconfig, _calls = _stub_publication_inputs(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(runner, "write_publication_output", lambda *_: None)

    with pytest.raises(runner.KindctlError, match="mode-0600 regular files"):
        runner.publish_images(kubeconfig, attempt, no_git_write=True)


def test_publish_requires_explicit_no_git_write_before_any_precondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runner,
        "validate_runtime_control",
        lambda *args: calls.append(args),
    )

    with pytest.raises(runner.KindctlError, match="requires --no-git-write"):
        runner.publish_images(
            tmp_path / "kubeconfig",
            tmp_path,
            no_git_write=False,
        )

    assert calls == []


def _write_memory_telemetry(
    runner: ModuleType,
    attempt: Path,
    *,
    complete: bool = False,
    sample_count: int = 2,
    sample_pid: int = 101,
) -> dict[str, object]:
    paths = runner.memory_telemetry_paths(attempt)
    paths["root"].mkdir(mode=0o700)
    identity: dict[str, object] = {"bootId": "test-boot", "pid": 101, "startTicks": 202}
    runner.write_exclusive(paths["baseline"], {"hostMemAvailableBaselineBytes": 10_000})
    runner.write_exclusive(paths["identity"], identity)
    runner.write_exclusive(paths["created"], {"created": True})
    runner.write_exclusive(
        paths["samples"],
        {
            "bootId": "test-boot",
            "complete": complete,
            "hostMemAvailableBaselineBytes": 10_000,
            "hostMemAvailableTroughBytes": 7_000,
            "pid": sample_pid,
            "sampleCount": sample_count,
            "startTicks": 202,
        },
    )
    return identity


def test_memory_sampler_trough_keeps_the_minimum_sample() -> None:
    runner = _load_runner()

    trough = None
    for sample in (9_000, 7_000, 8_000, 6_000, 6_500):
        trough = runner.next_memory_trough(trough, sample)

    assert trough == 6_000


def test_memory_sampler_finalize_fails_closed_on_missing_malformed_and_changed_state(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    missing = _attempt(tmp_path, "attempt-missing")
    with pytest.raises(runner.KindctlError, match="directory is unavailable"):
        runner.finish_memory_sampler(missing)

    malformed = _attempt(tmp_path, "attempt-malformed")
    malformed_paths = runner.memory_telemetry_paths(malformed)
    malformed_paths["root"].mkdir(mode=0o700)
    runner.write_exclusive(malformed_paths["identity"], {"not": "an identity"})
    with pytest.raises(runner.KindctlError, match="identity is malformed"):
        runner.finish_memory_sampler(malformed)

    changed = _attempt(tmp_path, "attempt-changed")
    _write_memory_telemetry(runner, changed, sample_pid=303)
    with pytest.raises(runner.KindctlError, match="identity changed"):
        runner.finish_memory_sampler(changed)


def test_stale_or_reused_sampler_pid_is_never_signaled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = _attempt(tmp_path)
    _write_memory_telemetry(runner, attempt)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runner, "process_matches", lambda _identity: False)
    monkeypatch.setattr(runner.os, "kill", lambda pid, signal: signals.append((pid, signal)))

    with pytest.raises(runner.KindctlError, match="identity changed before finalize"):
        runner.finish_memory_sampler(attempt)

    assert signals == []
    assert not runner.memory_telemetry_paths(attempt)["stop"].exists()


def test_incomplete_memory_sampler_state_cannot_finalize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = _attempt(tmp_path)
    _write_memory_telemetry(runner, attempt, complete=True, sample_count=1)
    matches = iter((True, False))
    monkeypatch.setattr(runner, "process_matches", lambda _identity: next(matches, False))

    with pytest.raises(runner.KindctlError, match="without complete telemetry"):
        runner.finish_memory_sampler(attempt)


@pytest.mark.parametrize("value", ["", "-1\n", "max\n", "1.0\n", "1 \n", "1\n2\n"])
def test_node_cgroup_memory_peak_parser_rejects_invalid_data(value: str) -> None:
    runner = _load_runner()

    with pytest.raises(runner.KindctlError, match="not a nonnegative integer"):
        runner.parse_nonnegative_bytes(value, "kind node cgroup memory.peak")


def test_node_cgroup_memory_peak_uses_the_bound_kind_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    container_id = "a" * 64
    measurements = {
        "nodes": [
            {
                "containerId": container_id,
                "name": "nohiki-control-plane",
                "startTime": "2026-08-04T12:00:00Z",
            }
        ]
    }
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: [{"Id": container_id, "State": {"StartedAt": "2026-08-04T12:00:00Z"}}],
    )
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(argv))
        return _completed(argv, "987654\n")

    monkeypatch.setattr(runner, "run_command", run)

    assert runner.kind_node_cgroup_memory_peak(measurements) == 987_654
    assert calls == [("podman", "exec", "nohiki-control-plane", "cat", "/sys/fs/cgroup/memory.peak")]


def test_flux_finalize_command_record_carries_both_memory_byte_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = _attempt(tmp_path)
    (tmp_path / "xdg").mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setattr(runner, "validate_runner_path", lambda: None)
    monkeypatch.setattr(runner, "validate_runtime_control", lambda *_args: None)
    monkeypatch.setattr(
        runner,
        "validate_publication_record",
        lambda *_args: {"clusterUid": "cluster-uid", "configMapUid": "configmap-uid"},
    )
    monkeypatch.setattr(
        runner,
        "runtime_binding",
        lambda *_args: ({"attempt": 1, "nodes": []}, "cluster-uid"),
    )
    monkeypatch.setattr(runner, "publication_configmap_binding", lambda *_args: "configmap-uid")
    monkeypatch.setattr(runner, "render_branch_manifest", lambda *_args: "final-hash")
    monkeypatch.setattr(
        runner,
        "command_json",
        lambda *_args, **_kwargs: {
            "metadata": {"uid": "flux-uid"},
            "spec": {"sync": {"path": "infra/k8s/gitops/clusters/local/bootstrap"}},
        },
    )
    monkeypatch.setattr(runner, "wait_root_kustomization", lambda *_args: "source-revision")
    monkeypatch.setattr(runner, "run_command", lambda argv, **_kwargs: _completed(argv))
    monkeypatch.setattr(runner, "wait_flux_instance", lambda *_args: "flux-uid")
    monkeypatch.setattr(runner, "FULL_CHILDREN", ())
    monkeypatch.setattr(runner, "kind_node_cgroup_memory_peak", lambda _measurements: 456)
    monkeypatch.setattr(
        runner,
        "finish_memory_sampler",
        lambda _attempt: {
            "hostMemAvailableBaselineBytes": 1_000,
            "hostMemAvailableTroughBytes": 877,
            "hostMemAvailableDropBytes": 123,
            "memoryAdmissionFloorBytes": 456,
            "memoryAdmissionFloorHeadroomBytes": 333,
            "memorySampleCount": 2,
        },
    )

    assert (
        runner.main(
            [
                "--attempt-dir",
                str(attempt),
                "flux-finalize",
                "--publication-record",
                str(attempt / "publication.json"),
            ]
        )
        == 0
    )

    record = json.loads((attempt / "commands/flux-finalize.json").read_text(encoding="utf-8"))
    assert record["hostMemAvailableBaselineBytes"] == 1_000
    assert record["hostMemAvailableTroughBytes"] == 877
    assert record["hostMemAvailableDropBytes"] == 123
    assert record["memoryAdmissionFloorBytes"] == 456
    assert record["memoryAdmissionFloorHeadroomBytes"] == 333
    assert record["memorySampleCount"] == 2
    assert record["kindNodeCgroupMemoryPeakBytes"] == 456
    assert record["result"] == "passed"


def test_memory_derivation_consumes_the_measured_drop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = _attempt(tmp_path)
    identity = _write_memory_telemetry(runner, attempt, complete=True)
    samples = runner.memory_telemetry_paths(attempt)["samples"]
    runner.write_atomic(
        samples,
        identity
        | {
            "complete": True,
            "hostMemAvailableBaselineBytes": 10_000,
            "hostMemAvailableTroughBytes": 7_000,
            "sampleCount": 2,
        },
    )
    matches = iter((True, False, False))
    monkeypatch.setattr(runner, "process_matches", lambda _identity: next(matches, False))
    monkeypatch.setattr(runner, "MEMORY_ADMISSION_FLOOR_BYTES", 4_000)

    result = runner.finish_memory_sampler(attempt)

    assert result == {
        "hostMemAvailableBaselineBytes": 10_000,
        "hostMemAvailableTroughBytes": 7_000,
        "hostMemAvailableDropBytes": 3_000,
        "memoryAdmissionFloorBytes": 4_000,
        "memoryAdmissionFloorHeadroomBytes": 1_000,
        "memorySampleCount": 2,
    }


def test_memory_derivation_rejects_a_drop_above_the_admission_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = _attempt(tmp_path)
    identity = _write_memory_telemetry(runner, attempt, complete=True)
    samples = runner.memory_telemetry_paths(attempt)["samples"]
    runner.write_atomic(
        samples,
        identity
        | {
            "complete": True,
            "hostMemAvailableBaselineBytes": 10_000,
            "hostMemAvailableTroughBytes": 5_000,
            "sampleCount": 2,
        },
    )
    matches = iter((True, False, False))
    monkeypatch.setattr(runner, "process_matches", lambda _identity: next(matches, False))
    monkeypatch.setattr(runner, "MEMORY_ADMISSION_FLOOR_BYTES", 4_000)

    with pytest.raises(runner.KindctlError, match="exceeds the admission floor"):
        runner.finish_memory_sampler(attempt)


def test_failed_finalize_still_stops_the_memory_sampler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    attempt = _attempt(tmp_path)
    (tmp_path / "xdg").mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setattr(runner, "validate_runner_path", lambda: None)
    monkeypatch.setattr(
        runner,
        "finalize_flux_runtime",
        lambda *_args: (_ for _ in ()).throw(runner.KindctlError("finalize failed")),
    )
    stops: list[Path] = []
    monkeypatch.setattr(runner, "finish_memory_sampler", lambda path: stops.append(path) or {})

    with pytest.raises(runner.KindctlError, match="finalize failed"):
        runner.main(
            [
                "--attempt-dir",
                str(attempt),
                "flux-finalize",
                "--publication-record",
                str(attempt / "publication.json"),
            ]
        )

    assert stops == [attempt]
